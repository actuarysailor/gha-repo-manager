from typing import Self

from github import Github

from repo_manager.utils import get_client, get_repo

from pydantic import BaseModel, ValidationInfo  # pylint: disable=E0611
from pydantic import Field, field_validator, model_validator


class Collaborator(BaseModel):
    type: str = Field("team", description="Type of reviewer, can be `user` or `team`")
    name: str = Field("user", description="Name of the reviewer, either a user or team name")
    permission: str = Field(
        "pull",
        description="Permission level of the reviewer, can be `pull` `triage`, "
        + "`push`, `maintain`, `admin`, or custom roles defined in the repo/org",
    )
    exists: bool = Field(
        True,
        description="Whether the collaborator should exist in the repo; "
        + "mark as false to remove the collaborator from the repo",
    )
    id: int = Field(0, description="ID of the reviewer, either a user or team ID")
    repositories_url: str = Field(None, description="URL to modify team permissions, only applicable for teams")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v) -> str:
        v = v.lower().capitalize()
        if v not in {"User", "Team"}:
            raise ValueError("Reviewer Type must be user or team.")
        return v

    @model_validator(mode="after")
    def initialize_id(self, info: ValidationInfo) -> Self:
        # Ensure type is capitalized (handles default values not caught by field_validator)
        self.type = self.type.lower().capitalize()

        if self.type == "Team" and "/" in self.name:
            raise ValueError(f"Team name should be just the slug, not '{self.name}'. Use '{self.name.split('/')[-1]}' instead.")

        # Only validate team/user existence when applying changes, not during check/validate
        action = info.context.get("action", "apply") if info.context else "apply"
        if action in ("check", "validate"):
            return self

        client: Github = get_client()
        if self.type == "User":
            self.id = int(client.get_user(self.name).id)
        elif self.type == "Team":
            org = get_repo().owner.login
            team = self.name
            try:
                github_object = client.get_organization(org).get_team_by_slug(team)
                self.repositories_url = github_object.repositories_url
                self.id = github_object.id
            except Exception as e:
                raise ValueError(
                    f"Team '{team}' not found in organization '{org}'. "
                    f"Ensure the team exists before applying changes. Error: {e}"
                ) from e
        return self
