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
        if ruleset.conditions.repository_name is not None:
            payload["conditions"]["repository_name"] = {
                "include": ruleset.conditions.repository_name.include,
                "exclude": ruleset.conditions.repository_name.exclude,
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


import re as _re


def _normalize_ref_pattern(pattern: str) -> str:
    """GitHub normalises 'refs/heads/foo' → 'refs/heads/**/foo' on write.
    Treat both forms as equivalent so we don't re-diff what we just applied."""
    return _re.sub(r"^refs/heads/(?!\*\*/)(.+)$", r"refs/heads/**/\1", pattern)


def _normalize_ref_condition(cond: dict | None) -> dict | None:
    """Normalise include/exclude lists in a ref_name or repository_name condition."""
    if cond is None:
        return None
    return {
        "include": sorted(_normalize_ref_pattern(p) for p in cond.get("include", [])),
        "exclude": sorted(_normalize_ref_pattern(p) for p in cond.get("exclude", [])),
    }


def _normalize_actor(actor: dict) -> dict:
    """GitHub always returns actor_id=null for OrganizationAdmin regardless of what we send."""
    actor = dict(actor)
    if actor.get("actor_type") == "OrganizationAdmin":
        actor["actor_id"] = None
    return actor


def _normalize_actors(actors: list[dict] | None) -> list[dict]:
    if not actors:
        return []
    return sorted(
        [_normalize_actor(a) for a in actors],
        key=lambda a: (a.get("actor_type", ""), a.get("actor_id") or 0, a.get("bypass_mode", "")),
    )


def _rule_satisfied(config_rule: dict, actual_rules: list[dict]) -> bool:
    """Return True if config_rule is satisfied by any rule in actual_rules.
    Only config-specified parameters are compared; GitHub may add extras
    (e.g. required_reviewers: []) that we should not flag as a diff."""
    for actual in actual_rules:
        if actual.get("type") != config_rule.get("type"):
            continue
        config_params = config_rule.get("parameters", {})
        actual_params = actual.get("parameters", {})
        if all(actual_params.get(k) == v for k, v in config_params.items()):
            return True
    return False


def _diff_ruleset(expected: Ruleset, actual: dict[str, Any]) -> dict[str, Any]:
    """Return a dict of field-level differences between expected config and the API response.

    Comparison rules that avoid false-positive diffs caused by GitHub normalisation:
    - bypass_actors: OrganizationAdmin actor_id is always null in API responses.
    - conditions: only compare keys present in the config; GitHub auto-adds
      ``repository_name: {include: ['~ALL']}`` to org-level rulesets.
    - rules: treat GitHub's rule list as a superset; GitHub may auto-add
      ``code_quality`` and ``copilot_code_review`` rules.  Only flag if a
      config rule is missing or has wrong parameters.  Per-rule parameters
      are also compared as a subset (GitHub adds ``required_reviewers: []").
    """
    diffs: dict[str, Any] = {}
    expected_payload = _ruleset_to_api_payload(expected)
    actual_clean = _strip_api_fields(actual)

    for key, expected_val in expected_payload.items():
        actual_val = actual_clean.get(key)

        if key == "bypass_actors":
            exp_norm = _normalize_actors(expected_val)
            act_norm = _normalize_actors(actual_val)
            if exp_norm != act_norm:
                diffs[key] = {"expected": exp_norm, "found": act_norm}

        elif key == "conditions":
            # Only compare condition keys the config specifies.
            # GitHub auto-adds repository_name and potentially others.
            actual_cond = actual_val or {}
            cond_diffs: dict[str, Any] = {}
            for cond_key, exp_cond_val in (expected_val or {}).items():
                act_cond_val = actual_cond.get(cond_key)
                if _normalize_ref_condition(exp_cond_val) != _normalize_ref_condition(act_cond_val):
                    cond_diffs[cond_key] = {"expected": exp_cond_val, "found": act_cond_val}
            if cond_diffs:
                diffs[key] = {"expected": expected_val, "found": actual_val}

        elif key == "rules":
            # Every config rule must be present and satisfied in GitHub's rules.
            # GitHub may add extra rules (code_quality, copilot_code_review) — ignore them.
            actual_rules_clean = _strip_api_fields(actual_val or [])
            expected_rules_clean = _strip_api_fields(expected_val or [])
            unsatisfied = [r for r in expected_rules_clean if not _rule_satisfied(r, actual_rules_clean)]
            if unsatisfied:
                diffs[key] = {"expected": expected_rules_clean, "found": actual_rules_clean}

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
