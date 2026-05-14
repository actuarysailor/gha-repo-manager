from typing import Any

from actions_toolkit import core as actions_toolkit

from repo_manager.schemas.ruleset import Ruleset
from repo_manager.gh.rulesets import _ruleset_to_api_payload, _diff_ruleset
from repo_manager.gh.enterprise_settings import _enterprise_url


def check_enterprise_rulesets(
    requester,
    enterprise: str,
    config_rulesets: list[Ruleset],
) -> tuple[bool, dict[str, Any] | None]:
    """Check an enterprise's rulesets against expected configuration."""
    base = _enterprise_url(requester, enterprise)
    try:
        _, existing_list = requester.requestJsonAndCheck("GET", f"{base}/rulesets")
    except Exception as exc:
        actions_toolkit.warning(f"Unable to fetch rulesets for enterprise '{enterprise}': {exc}")
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
            _, full_actual = requester.requestJsonAndCheck("GET", f"{base}/rulesets/{match['id']}")
        except Exception as exc:
            actions_toolkit.warning(
                f"Unable to fetch enterprise ruleset detail '{config_rs.name}' (id={match['id']}): {exc}"
            )
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


def update_enterprise_rulesets(
    requester,
    enterprise: str,
    config_rulesets: list[Ruleset],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create, update, or delete enterprise rulesets to reconcile state with config."""
    errors: list[dict] = []
    messages: list[str] = []
    config_by_name = {rs.name: rs for rs in config_rulesets}
    base = _enterprise_url(requester, enterprise)

    def _handle_exc(exc: Exception, op_type: str, name: str) -> None:
        from github import GithubException
        if isinstance(exc, GithubException) and exc.status == 403:
            actions_toolkit.warning(f"Unable to {op_type} enterprise ruleset '{name}': {exc.message} (feature unavailable)")
        else:
            errors.append({"type": f"enterprise-ruleset-{op_type}", "name": name, "error": str(exc)})

    for name in diffs.get("missing", []):
        payload = _ruleset_to_api_payload(config_by_name[name])
        try:
            requester.requestJsonAndCheck("POST", f"{base}/rulesets", input=payload)
            actions_toolkit.info(f"Created enterprise ruleset '{name}'")
            messages.append(f"Created enterprise ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "create", name)

    for entry in diffs.get("extra", []):
        name = entry["name"]
        for rid in entry["_ids"]:
            try:
                requester.requestJsonAndCheck("DELETE", f"{base}/rulesets/{rid}")
                actions_toolkit.info(f"Deleted enterprise ruleset '{name}' (id={rid})")
                messages.append(f"Deleted enterprise ruleset '{name}' (id={rid})")
            except Exception as exc:
                _handle_exc(exc, "delete", name)

    for name, ruleset_diff in diffs.get("diff", {}).items():
        payload = _ruleset_to_api_payload(config_by_name[name])
        rid = ruleset_diff["_id"]
        try:
            requester.requestJsonAndCheck("PUT", f"{base}/rulesets/{rid}", input=payload)
            actions_toolkit.info(f"Updated enterprise ruleset '{name}'")
            messages.append(f"Updated enterprise ruleset '{name}'")
        except Exception as exc:
            _handle_exc(exc, "update", name)

    return errors, messages
