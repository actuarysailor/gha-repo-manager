from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Organization import Organization

from repo_manager.schemas.org_settings import OrgSettings

# Fields exposed by GET /orgs/{org} that map directly to PATCH payload keys
# (after the 'website' -> 'blog' rename in to_api_payload).
_READABLE_FIELDS = {
    "description",
    "blog",  # website in our schema
    "email",
    "twitter_username",
    "location",
    "company",
    "default_repository_permission",
    "members_can_create_repositories",
    "members_can_create_public_repositories",
    "members_can_create_private_repositories",
    "members_can_fork_private_repositories",
    "web_commit_signoff_required",
    "members_can_create_pages",
    "members_can_create_public_pages",
    "has_organization_projects",
    "has_repository_projects",
}

# Map from OrgSettings field name to GitHub API response key
_SCHEMA_TO_API = {"website": "blog"}


def check_org_settings(org: Organization, settings: OrgSettings) -> tuple[bool, dict[str, Any] | None]:
    """Check org settings against expected config.

    Args:
        org: PyGitHub Organization object
        settings: OrgSettings config object

    Returns:
        Tuple of (all_match, diffs_dict)
    """
    try:
        _, actual = org._requester.requestJsonAndCheck("GET", org.url)
    except Exception as exc:
        actions_toolkit.warning(f"Unable to fetch org settings for {org.login}: {exc}")
        return False, {"error": str(exc)}

    diffs: dict[str, Any] = {}
    for field_name, expected_val in settings.model_dump(exclude_none=True).items():
        api_key = _SCHEMA_TO_API.get(field_name, field_name)
        # Normalise enums to their string values
        if hasattr(expected_val, "value"):
            expected_val = expected_val.value
        actual_val = actual.get(api_key)
        if expected_val != actual_val:
            diffs[field_name] = {"expected": expected_val, "found": actual_val}

    if diffs:
        return False, diffs
    return True, None


def update_org_settings(
    org: Organization,
    settings: OrgSettings,
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Patch org settings to match config.

    Args:
        org: PyGitHub Organization object
        settings: OrgSettings config object
        diffs: The diffs dict from check_org_settings (used to build the minimal payload)

    Returns:
        Tuple of (errors, summary_messages)
    """
    errors: list[dict] = []
    messages: list[str] = []

    # Build payload from only the differing fields
    full_payload = settings.to_api_payload()
    payload = {
        _SCHEMA_TO_API.get(k, k): full_payload[_SCHEMA_TO_API.get(k, k)]
        for k in diffs
        if _SCHEMA_TO_API.get(k, k) in full_payload
    }

    if not payload:
        return errors, messages

    try:
        org._requester.requestJsonAndCheck("PATCH", org.url, input=payload)
        changed = ", ".join(diffs.keys())
        actions_toolkit.info(f"Updated org settings for {org.login}: {changed}")
        messages.append(f"Updated org settings: {changed}")
    except Exception as exc:
        errors.append({"type": "org-settings-update", "error": str(exc)})

    return errors, messages
