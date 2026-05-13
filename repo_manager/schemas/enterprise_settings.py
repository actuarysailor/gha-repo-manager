from enum import Enum

from pydantic import BaseModel, Field

OptBool = bool | None
OptStr = str | None


class EnabledOrganizations(str, Enum):
    all = "all"
    none = "none"
    selected = "selected"


class AllowedActions(str, Enum):
    all = "all"
    local_only = "local_only"
    selected = "selected"


class EnterpriseActionsPermissions(BaseModel):
    """Maps to GET/PUT /enterprises/{enterprise}/actions/permissions"""

    enabled_organizations: EnabledOrganizations | None = Field(
        None,
        description="Which organizations can use GitHub Actions: all | none | selected",
    )
    allowed_actions: AllowedActions | None = Field(
        None,
        description="Which actions are permitted: all | local_only | selected",
    )
    # Only relevant when allowed_actions = selected
    github_owned_allowed: OptBool = Field(
        None, description="Allow GitHub-owned actions when allowed_actions='selected'"
    )
    verified_allowed: OptBool = Field(
        None, description="Allow verified creator actions when allowed_actions='selected'"
    )
    patterns_allowed: list[str] | None = Field(
        None,
        description="Glob patterns for allowed actions when allowed_actions='selected' (e.g. 'octo-org/*')",
    )

    def to_permissions_payload(self) -> dict:
        payload = {}
        if self.enabled_organizations is not None:
            payload["enabled_organizations"] = self.enabled_organizations.value
        if self.allowed_actions is not None:
            payload["allowed_actions"] = self.allowed_actions.value
        return payload

    def to_selected_actions_payload(self) -> dict | None:
        """Returns payload for the selected-actions sub-endpoint, or None if not needed."""
        if self.allowed_actions != AllowedActions.selected:
            return None
        payload = {}
        if self.github_owned_allowed is not None:
            payload["github_owned_allowed"] = self.github_owned_allowed
        if self.verified_allowed is not None:
            payload["verified_allowed"] = self.verified_allowed
        if self.patterns_allowed is not None:
            payload["patterns_allowed"] = self.patterns_allowed
        return payload or None


class EnterpriseSettings(BaseModel):
    """Enterprise-level settings managed via the GitHub REST API."""

    actions_permissions: EnterpriseActionsPermissions | None = Field(
        None, description="Enterprise-wide GitHub Actions permissions"
    )
