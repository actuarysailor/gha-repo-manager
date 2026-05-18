from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Repository import Repository

from repo_manager.schemas.ruleset import Ruleset

# API-only fields that must be stripped before diffing
_IGNORE_FIELDS = {
    "id",
    "source",
    "source_type",
    "created_at",
    "updated_at",
    "node_id",
    "_links",
    "current_user_can_bypass",
}


def _ruleset_to_api_payload(ruleset: Ruleset) -> dict[str, Any]:
    """Convert a Ruleset schema to a GitHub API payload dict."""
    payload: dict[str, Any] = {
        "name": ruleset.name,
        "target": ruleset.target.value,
        "enforcement": ruleset.enforcement.value,
    }
    if ruleset.bypass_actors is not None:
        payload["bypass_actors"] = [
            {
                "actor_id": ba.actor_id,
                "actor_type": ba.actor_type.value,
                "bypass_mode": ba.bypass_mode.value,
            }
            for ba in ruleset.bypass_actors
        ]
    if ruleset.conditions is not None:
        payload["conditions"] = {}
        if ruleset.conditions.ref_name is not None:
            payload["conditions"]["ref_name"] = {
                "include": ruleset.conditions.ref_name.include,
                "exclude": ruleset.conditions.ref_name.exclude,
            }
    if ruleset.rules is not None:
        payload["rules"] = [
            {"type": rule.type, **({"parameters": rule.parameters} if rule.parameters else {})}
            for rule in ruleset.rules
        ]
    return payload


def _strip_api_fields(obj: Any) -> Any:
    """Recursively strip API-only metadata fields from a dict/list for diffing."""
    if isinstance(obj, dict):
        return {k: _strip_api_fields(v) for k, v in obj.items() if k not in _IGNORE_FIELDS}
    if isinstance(obj, list):
        return [_strip_api_fields(item) for item in obj]
    return obj


def _normalise_rules(rules: list[dict] | None) -> list[dict]:
    """Sort rules by type for stable comparison."""
    if rules is None:
        return []
    return sorted(_strip_api_fields(rules), key=lambda r: r.get("type", ""))


def _diff_ruleset(expected: Ruleset, actual: dict[str, Any]) -> dict[str, Any]:
    """Return a dict of field-level differences between expected config and the API response."""
    diffs: dict[str, Any] = {}
    expected_payload = _ruleset_to_api_payload(expected)
    actual_clean = _strip_api_fields(actual)

    for key, expected_val in expected_payload.items():
        actual_val = actual_clean.get(key)
        # Normalise rule lists so order doesn't matter
        if key == "rules":
            expected_norm = _normalise_rules(expected_val)
            actual_norm = _normalise_rules(actual_val)
            if expected_norm != actual_norm:
                diffs[key] = {"expected": expected_norm, "found": actual_norm}
        elif expected_val != actual_val:
            diffs[key] = {"expected": expected_val, "found": actual_val}
    return diffs


def check_repo_rulesets(repo: Repository, config_rulesets: list[Ruleset]) -> tuple[bool, dict[str, Any] | None]:
    """Check a repo's rulesets against the expected configuration.

    Args:
        repo: PyGitHub Repository object
        config_rulesets: List of Ruleset config objects from the settings file

    Returns:
        Tuple of (all_match, diffs_dict). diffs_dict is None when everything matches.
    """
    try:
        _, existing_list = repo._requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets")
    except Exception as exc:
        from github import GithubException

        if isinstance(exc, GithubException) and exc.status == 403:
            actions_toolkit.warning(f"Unable to fetch rulesets for {repo.full_name}: {exc}")
            return True, None  # feature unavailable — not an actionable diff
        actions_toolkit.warning(f"Unable to fetch rulesets for {repo.full_name}: {exc}")
        return False, {"error": str(exc)}

    # Index existing rulesets by name (names aren't enforced unique by GitHub, so keep a list)
    existing_by_name: dict[str, list[dict]] = {}
    for rs in existing_list:
        existing_by_name.setdefault(rs["name"], []).append(rs)

    missing: list[str] = []
    extra: list[dict] = []
    diff_map: dict[str, Any] = {}

    for config_rs in config_rulesets:
        matches = existing_by_name.get(config_rs.name, [])

        if config_rs.exists is False:
            if matches:
                extra.append({"name": config_rs.name, "_ids": [rs["id"] for rs in matches]})
            continue

        if not matches:
            missing.append(config_rs.name)
            continue

        # Fetch full detail for the first match (names should be unique per target in practice)
        match = matches[0]
        try:
            _, full_actual = repo._requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets/{match['id']}")
        except Exception as exc:
            actions_toolkit.warning(f"Unable to fetch ruleset detail for '{config_rs.name}' (id={match['id']}): {exc}")
            full_actual = match

        ruleset_diffs = _diff_ruleset(config_rs, full_actual)
        if ruleset_diffs:
            diff_map[config_rs.name] = {**ruleset_diffs, "_id": match["id"]}

    result: dict[str, Any] = {}
    if missing:
        result["missing"] = missing
    if extra:
        result["extra"] = extra
    if diff_map:
        result["diff"] = diff_map

    if result:
        return False, result
    return True, None


def update_rulesets(
    repo: Repository,
    config_rulesets: list[Ruleset],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create, update, or delete rulesets to reconcile repo state with config.

    Args:
        repo: PyGitHub Repository object
        config_rulesets: Full list of Ruleset config objects
        diffs: The diffs dict returned by check_repo_rulesets

    Returns:
        Tuple of (errors, summary_messages)
    """
    errors: list[dict] = []
    messages: list[str] = []
    config_by_name = {rs.name: rs for rs in config_rulesets}

    def _handle_exc(exc: Exception, op_type: str, name: str) -> None:
        from github import GithubException

        if isinstance(exc, GithubException) and exc.status == 403:
            actions_toolkit.warning(
                f"Unable to {op_type} ruleset '{name}': {exc.message} (feature unavailable — upgrade plan or make repo public)"
            )
        else:
            errors.append({"type": f"ruleset-{op_type}", "name": name, "error": str(exc)})

    # Create missing rulesets
    for name in diffs.get("missing", []):
        rs = config_by_name[name]
        payload = _ruleset_to_api_payload(rs)
        try:
            repo._requester.requestJsonAndCheck("POST", f"{repo.url}/rulesets", input=payload)
            actions_toolkit.info(f"Created ruleset '{name}'")
            messages.append(f"Created ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "create", name)

    # Delete extra rulesets
    for entry in diffs.get("extra", []):
        name = entry["name"]
        for rid in entry["_ids"]:
            try:
                repo._requester.requestJsonAndCheck("DELETE", f"{repo.url}/rulesets/{rid}")
                actions_toolkit.info(f"Deleted ruleset '{name}' (id={rid})")
                messages.append(f"Deleted ruleset '{name}' (id={rid})")
            except Exception as exc:
                _handle_exc(exc, "delete", name)

    # Update differing rulesets
    for name, ruleset_diff in diffs.get("diff", {}).items():
        rs = config_by_name[name]
        rid = ruleset_diff["_id"]
        payload = _ruleset_to_api_payload(rs)
        try:
            repo._requester.requestJsonAndCheck("PUT", f"{repo.url}/rulesets/{rid}", input=payload)
            actions_toolkit.info(f"Updated ruleset '{name}'")
            messages.append(f"Updated ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "update", name)

    return errors, messages
