from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Organization import Organization

from repo_manager.schemas.ruleset import Ruleset
from repo_manager.gh.rulesets import (
    _ruleset_to_api_payload,
    _diff_ruleset,
)


def _org_ruleset_payload(rs: Ruleset) -> dict:
    """Build an org-ruleset payload, injecting repository_name condition if absent.
    GitHub's org ruleset API requires repository_name in conditions."""
    payload = _ruleset_to_api_payload(rs)
    if "conditions" not in payload:
        payload["conditions"] = {}
    if "repository_name" not in payload["conditions"]:
        payload["conditions"]["repository_name"] = {"include": ["~ALL"], "exclude": []}
    return payload


def check_org_rulesets(org: Organization, config_rulesets: list[Ruleset]) -> tuple[bool, dict[str, Any] | None]:
    """Check an org's rulesets against the expected configuration."""
    try:
        _, existing_list = org._requester.requestJsonAndCheck("GET", f"{org.url}/rulesets")
    except Exception as exc:
        from github import GithubException

        if isinstance(exc, GithubException) and exc.status == 403:
            actions_toolkit.warning(f"Unable to fetch rulesets for org {org.login}: {exc}")
            return True, None  # feature unavailable — not an actionable diff
        actions_toolkit.warning(f"Unable to fetch rulesets for org {org.login}: {exc}")
        return False, {"error": str(exc)}

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

        match = matches[0]
        try:
            _, full_actual = org._requester.requestJsonAndCheck("GET", f"{org.url}/rulesets/{match['id']}")
        except Exception as exc:
            actions_toolkit.warning(f"Unable to fetch ruleset detail '{config_rs.name}' (id={match['id']}): {exc}")
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

    return (False, result) if result else (True, None)


def update_org_rulesets(
    org: Organization,
    config_rulesets: list[Ruleset],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create, update, or delete org rulesets to reconcile state with config."""
    errors: list[dict] = []
    messages: list[str] = []
    config_by_name = {rs.name: rs for rs in config_rulesets}

    def _handle_exc(exc: Exception, op_type: str, name: str) -> None:
        from github import GithubException

        if isinstance(exc, GithubException) and exc.status == 403:
            actions_toolkit.warning(f"Unable to {op_type} org ruleset '{name}': {exc.message} (feature unavailable)")
        else:
            errors.append({"type": f"org-ruleset-{op_type}", "name": name, "error": str(exc)})

    for name in diffs.get("missing", []):
        rs = config_by_name[name]
        payload = _org_ruleset_payload(rs)
        try:
            org._requester.requestJsonAndCheck("POST", f"{org.url}/rulesets", input=payload)
            actions_toolkit.info(f"Created org ruleset '{name}'")
            messages.append(f"Created org ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "create", name)

    for entry in diffs.get("extra", []):
        name = entry["name"]
        for rid in entry["_ids"]:
            try:
                org._requester.requestJsonAndCheck("DELETE", f"{org.url}/rulesets/{rid}")
                actions_toolkit.info(f"Deleted org ruleset '{name}' (id={rid})")
                messages.append(f"Deleted org ruleset '{name}' (id={rid})")
            except Exception as exc:
                _handle_exc(exc, "delete", name)

    for name, ruleset_diff in diffs.get("diff", {}).items():
        rs = config_by_name[name]
        rid = ruleset_diff["_id"]
        payload = _org_ruleset_payload(rs)
        import json as _json
        actions_toolkit.debug(f"PUT org ruleset '{name}' payload: {_json.dumps(payload)}")
        try:
            _, response = org._requester.requestJsonAndCheck("PUT", f"{org.url}/rulesets/{rid}", input=payload)
            actions_toolkit.debug(f"PUT org ruleset '{name}' response rules: {_json.dumps(response.get('rules', []))}")
            actions_toolkit.info(f"Updated org ruleset '{name}'")
            messages.append(f"Updated org ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "update", name)

    return errors, messages
