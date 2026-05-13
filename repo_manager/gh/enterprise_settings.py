from typing import Any

from actions_toolkit import core as actions_toolkit

from repo_manager.schemas.enterprise_settings import EnterpriseSettings, AllowedActions


# The Enterprise object from PyGitHub has very limited support, so we work
# entirely through raw _requester.requestJsonAndCheck calls.
# The caller passes the requester and enterprise slug directly.


def _enterprise_url(requester, enterprise: str) -> str:
    """Build the base URL for enterprise API calls."""
    base = requester.base_url.rstrip("/")
    return f"{base}/enterprises/{enterprise}"


def check_enterprise_settings(
    requester,
    enterprise: str,
    config: EnterpriseSettings,
) -> tuple[bool, dict[str, Any] | None]:
    """Check enterprise-level settings against expected configuration."""
    diffs: dict[str, Any] = {}
    base = _enterprise_url(requester, enterprise)

    if config.actions_permissions is not None:
        ap = config.actions_permissions
        try:
            _, actual = requester.requestJsonAndCheck("GET", f"{base}/actions/permissions")
        except Exception as exc:
            actions_toolkit.warning(f"Could not fetch enterprise actions permissions: {exc}")
            return False, {"error": str(exc)}

        perms_diff: dict[str, Any] = {}
        if (
            ap.enabled_organizations is not None
            and actual.get("enabled_organizations") != ap.enabled_organizations.value
        ):
            perms_diff["enabled_organizations"] = {
                "expected": ap.enabled_organizations.value,
                "found": actual.get("enabled_organizations"),
            }
        if ap.allowed_actions is not None and actual.get("allowed_actions") != ap.allowed_actions.value:
            perms_diff["allowed_actions"] = {
                "expected": ap.allowed_actions.value,
                "found": actual.get("allowed_actions"),
            }

        if ap.allowed_actions == AllowedActions.selected and (
            ap.github_owned_allowed is not None or ap.verified_allowed is not None or ap.patterns_allowed is not None
        ):
            try:
                _, actual_sel = requester.requestJsonAndCheck("GET", f"{base}/actions/permissions/selected-actions")
            except Exception as exc:
                actions_toolkit.warning(f"Could not fetch enterprise selected-actions: {exc}")
                actual_sel = {}

            for field in ("github_owned_allowed", "verified_allowed", "patterns_allowed"):
                expected_val = getattr(ap, field)
                if expected_val is not None and actual_sel.get(field) != expected_val:
                    perms_diff[field] = {"expected": expected_val, "found": actual_sel.get(field)}

        if perms_diff:
            diffs["actions_permissions"] = perms_diff

    return (False, diffs) if diffs else (True, None)


def update_enterprise_settings(
    requester,
    enterprise: str,
    config: EnterpriseSettings,
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Apply enterprise-level settings to reconcile state with config."""
    errors: list[dict] = []
    messages: list[str] = []
    base = _enterprise_url(requester, enterprise)

    if "actions_permissions" in diffs and config.actions_permissions is not None:
        ap = config.actions_permissions
        perms_payload = ap.to_permissions_payload()
        if perms_payload:
            try:
                requester.requestJsonAndCheck("PUT", f"{base}/actions/permissions", input=perms_payload)
                actions_toolkit.info("Updated enterprise actions permissions")
                messages.append("Updated enterprise actions permissions")
            except Exception as exc:
                errors.append({"type": "enterprise-actions-permissions", "error": str(exc)})

        sel_payload = ap.to_selected_actions_payload()
        if sel_payload:
            try:
                requester.requestJsonAndCheck("PUT", f"{base}/actions/permissions/selected-actions", input=sel_payload)
                actions_toolkit.info("Updated enterprise selected-actions policy")
                messages.append("Updated enterprise selected-actions policy")
            except Exception as exc:
                errors.append({"type": "enterprise-selected-actions", "error": str(exc)})

    return errors, messages
