import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

OptBool = bool | None
OptStr = str | None


class OrgDefaultRepoPermission(str, Enum):
    none = "none"
    read = "read"
    write = "write"
    admin = "admin"


class OrgSettings(BaseModel):
    """Maps to PATCH /orgs/{org}.
    Any field left as None will be skipped (not overwritten).
    """

    description: OptStr = Field(None, description="A short description of the organization")
    website: OptStr = Field(None, description="URL of the organization's website (GitHub API field: 'blog')")
    email: OptStr = Field(None, description="Publicly visible email address for the organization")
    twitter_username: OptStr = Field(None, description="Twitter username of the organization")
    location: OptStr = Field(None, description="Location of the organization")
    company: OptStr = Field(None, description="Company name")
    default_repository_permission: OrgDefaultRepoPermission | None = Field(
        None,
        description="Default permission for org members on all org repos: none | read | write | admin",
    )
    members_can_create_repositories: OptBool = Field(
        None, description="Allow org members to create new repositories"
    )
    members_can_create_public_repositories: OptBool = Field(
        None, description="Allow org members to create public repositories"
    )
    members_can_create_private_repositories: OptBool = Field(
        None, description="Allow org members to create private repositories"
    )
    members_can_fork_private_repositories: OptBool = Field(
        None, description="Allow org members to fork private repositories"
    )
    web_commit_signoff_required: OptBool = Field(
        None, description="Require contributors to sign off on web-based commits"
    )
    members_can_create_pages: OptBool = Field(
        None, description="Allow org members to create GitHub Pages sites"
    )
    members_can_create_public_pages: OptBool = Field(
        None, description="Allow org members to create public GitHub Pages sites"
    )
    has_organization_projects: OptBool = Field(
        None, description="Enable org-level Projects boards"
    )
    has_repository_projects: OptBool = Field(
        None, description="Enable Projects boards on org repos by default"
    )

    def to_api_payload(self) -> dict:
        """Return only non-None fields mapped to the GitHub API's field names."""
        field_map = {
            "website": "blog",  # API uses 'blog' for the website URL
        }
        payload = {}
        for field_name, value in self.model_dump(exclude_none=True).items():
            api_key = field_map.get(field_name, field_name)
            payload[api_key] = value.value if hasattr(value, "value") else value
        return payload


class OrgSecretVisibility(str, Enum):
    all = "all"
    private = "private"
    selected = "selected"


class SecretEnvError(Exception): ...


class OrgSecret(BaseModel):
    """An org-level Actions or Dependabot secret with visibility controls."""

    type: str = Field(
        "actions",
        description="Type of secret: 'actions' or 'dependabot'",
    )
    key: str = Field(description="The secret name")
    env: OptStr = Field(None, description="Environment variable on the runner to read the value from")
    value: OptStr = Field(None, description="Literal value — avoid for real secrets")
    required: OptBool = Field(
        True,
        description="If false and the env var is not set, skip without error",
    )
    visibility: OrgSecretVisibility = Field(
        default=OrgSecretVisibility.all,
        description="Which repos can access this secret: all | private | selected",
    )
    selected_repositories: list[str] | None = Field(
        None,
        description="Repo names (owner/repo or just repo) when visibility='selected'",
    )
    exists: OptBool = Field(True, description="Set to false to delete the secret")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: OptStr, info: ValidationInfo) -> OptStr:
        if v is None:
            return None
        if info.data.get("env") is not None:
            raise ValueError("Cannot set both 'env' and 'value' — remove one.")
        return v

    @property
    def expected_value(self) -> str:
        if self.value is not None:
            return self.value
        env_var = os.environ.get(self.env)
        if env_var is None:
            if self.required:
                raise SecretEnvError(f"Environment variable '{self.env}' is not set")
            return None
        return env_var
