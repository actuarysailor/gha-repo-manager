import yaml
from pydantic import BaseModel, Field  # pylint: disable=E0611

from .branch_protection import BranchProtection
from .file import BranchFiles
from .label import Label
from .org_settings import OrgSecret, OrgSettings
from .ruleset import Ruleset
from .secret import Secret
from .settings import Settings
from .environment import Environment
from .collaborator import Collaborator
from .team import Team


class RepoManagerConfig(BaseModel):
    # ── Repo-scoped sections ──────────────────────────────────────────────────
    settings: Settings | None = None
    branch_protections: list[BranchProtection] | None = Field(
        None, description="Branch protections in the repo to manage"
    )
    rulesets: list[Ruleset] | None = Field(None, description="Branch/tag rulesets in the repo to manage")
    secrets: list[Secret] | None = Field(None, description="Secrets in the repo to manage")
    variables: list[Secret] | None = Field(None, description="Variables in the repo to manage")
    labels: list[Label] | None = Field(None, description="Labels in the repo to manage")
    batch_file_operations: list[BranchFiles] | None = Field(None, description="Files in the repo to manage")
    collaborators: list[Collaborator] | None = Field(None, description="Collaborators in the repo to manage")
    environments: list[Environment] | None = Field(None, description="Deployment Environments in the repo to manage")

    # ── Org-scoped sections ───────────────────────────────────────────────────
    org_settings: OrgSettings | None = Field(None, description="Organization-level settings to manage")
    teams: list[Team] | None = Field(None, description="Teams in the org to manage")
    org_rulesets: list[Ruleset] | None = Field(None, description="Org-level branch/tag rulesets to manage")
    org_labels: list[Label] | None = Field(None, description="Org-level labels to manage")
    org_secrets: list[OrgSecret] | None = Field(None, description="Org-level Actions/Dependabot secrets to manage")
    org_variables: list[OrgSecret] | None = Field(None, description="Org-level Actions variables to manage")

    @property
    def secrets_dict(self):
        return {secret.key: secret for secret in self.secrets} if self.secrets is not None else {}

    @property
    def variables_dict(self):
        return {variable.key: variable for variable in self.variables} if self.variables is not None else {}

    @property
    def labels_dict(self):
        return {label.expected_name: label for label in self.labels} if self.labels is not None else {}

    @property
    def branch_protections_dict(self):
        return (
            {branch_protection.name: branch_protection for branch_protection in self.branch_protections}
            if self.branch_protections is not None
            else {}
        )

    @property
    def environments_dict(self):
        return (
            {environment.name: environment for environment in self.environments}
            if self.environments is not None
            else {}
        )

    @property
    def collaborators_dict(self):
        return (
            {collaborator.name: collaborator for collaborator in self.collaborators}
            if self.collaborators is not None
            else {}
        )

    @property
    def teams_dict(self):
        return {team.name: team for team in self.teams} if self.teams is not None else {}

    @property
    def org_rulesets_dict(self):
        return {ruleset.name: ruleset for ruleset in self.org_rulesets} if self.org_rulesets is not None else {}

    @property
    def org_secrets_dict(self):
        return {secret.key: secret for secret in self.org_secrets} if self.org_secrets is not None else {}

    @property
    def org_variables_dict(self):
        return {variable.key: variable for variable in self.org_variables} if self.org_variables is not None else {}


def load_config(filename: str, action: str = "validate") -> RepoManagerConfig:
    """Loads a yaml file into a RepoManagerconfig

    Args:
        filename: Path to the YAML settings file
        action: The action being performed ('validate', 'check', or 'apply').
                Used to skip expensive validations during check mode.
    """
    with open(filename, encoding="utf-8") as fh:
        this_dict = yaml.safe_load(fh)

    return RepoManagerConfig.model_validate(this_dict, context={"action": action})
