from enum import Enum

from pydantic import BaseModel, Field

OptBool = bool | None
OptStr = str | None


class TeamPrivacy(str, Enum):
    secret = "secret"  # nosec B105 — GitHub team privacy value, not a password  # only visible to org owners and team members
    closed = "closed"  # visible to all org members


class TeamRole(str, Enum):
    member = "member"
    maintainer = "maintainer"


class TeamMember(BaseModel):
    username: str = Field(description="GitHub login of the team member")
    role: TeamRole = Field(
        default=TeamRole.member,
        description="Role of the member within the team: 'member' or 'maintainer'",
    )
    exists: OptBool = Field(True, description="Set to false to remove this member from the team")


class TeamRepository(BaseModel):
    name: str = Field(
        description=(
            "Repository to grant team access to. Accepts 'owner/repo' or just 'repo' "
            "(the org is inferred from the org being managed)."
        )
    )
    permission: str = Field(
        "pull",
        description="Permission level: pull | triage | push | maintain | admin | <custom role>",
    )
    exists: OptBool = Field(True, description="Set to false to remove this repo from the team's access list")


class Team(BaseModel):
    name: str = Field(description="The name of the team (display name)")
    slug: OptStr = Field(
        None,
        description=(
            "The team slug used in URLs. If omitted it is derived from 'name' by GitHub. "
            "Required when referencing an existing team whose slug differs from its name."
        ),
    )
    description: OptStr = Field(None, description="A description of the team")
    privacy: TeamPrivacy = Field(
        default=TeamPrivacy.closed,
        description="Visibility of the team: 'secret' (members + owners only) or 'closed' (all org members)",
    )
    parent_team_slug: OptStr = Field(
        None,
        description="Slug of the parent team (creates a nested team hierarchy). Set to null to make it a top-level team.",
    )
    members: list[TeamMember] | None = Field(None, description="Members of the team")
    repositories: list[TeamRepository] | None = Field(None, description="Repositories the team should have access to")
    exists: OptBool = Field(True, description="Set to false to delete this team")
