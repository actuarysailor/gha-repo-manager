from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

OptBool = bool | None
OptStr = str | None


class RuleTarget(str, Enum):
    branch = "branch"
    tag = "tag"
    push = "push"


class RuleEnforcement(str, Enum):
    disabled = "disabled"
    active = "active"
    evaluate = "evaluate"


class BypassActorType(str, Enum):
    Integration = "Integration"
    OrganizationAdmin = "OrganizationAdmin"
    RepositoryRole = "RepositoryRole"
    Team = "Team"
    DeployKey = "DeployKey"


class BypassMode(str, Enum):
    always = "always"
    pull_request = "pull_request"


class BypassActor(BaseModel):
    actor_id: int = Field(description="The ID of the actor that can bypass a ruleset")
    actor_type: BypassActorType = Field(description="The type of actor that can bypass a ruleset")
    bypass_mode: BypassMode = Field(
        default=BypassMode.always,
        description="When the actor can bypass the ruleset. 'pull_request' means only when merging a PR.",
    )


class RefNameCondition(BaseModel):
    include: list[str] = Field(
        default_factory=list,
        description=(
            "Array of ref name patterns to include. "
            "Use '~DEFAULT_BRANCH' for the default branch, '~ALL' for all branches, "
            "or 'refs/heads/<pattern>' for specific branches."
        ),
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Array of ref name patterns to exclude.",
    )


class RepositoryNameCondition(BaseModel):
    include: list[str] = Field(default_factory=list, description="Repository name patterns to include. Use '~ALL' for all.")
    exclude: list[str] = Field(default_factory=list, description="Repository name patterns to exclude.")


class RulesetConditions(BaseModel):
    ref_name: RefNameCondition | None = None
    repository_name: RepositoryNameCondition | None = Field(
        None,
        description="Filter by repository name (required for org-level rulesets). Defaults to '~ALL' when omitted.",
    )


class RulesetRule(BaseModel):
    """A single rule within a ruleset. The 'type' field identifies the rule.

    Common rule types (no parameters required):
      creation, deletion, required_linear_history, required_signatures, non_fast_forward

    Common rule types (parameters required):
      update                      -- parameters: {update_allows_fetch_and_merge: bool}
      pull_request                -- parameters: {required_approving_review_count, dismiss_stale_reviews_on_push,
                                                   require_code_owner_review, require_last_push_approval,
                                                   required_review_thread_resolution}
      required_status_checks      -- parameters: {required_status_checks: [{context, integration_id?}],
                                                   strict_required_status_checks_policy?,
                                                   do_not_enforce_on_create?}
      required_deployments        -- parameters: {required_deployment_environments: [str]}
      commit_message_pattern      -- parameters: {operator, pattern, name?, negate?}
      commit_author_email_pattern -- parameters: {operator, pattern, name?, negate?}
      committer_email_pattern     -- parameters: {operator, pattern, name?, negate?}
      branch_name_pattern         -- parameters: {operator, pattern, name?, negate?}
      tag_name_pattern            -- parameters: {operator, pattern, name?, negate?}
      file_path_restriction       -- parameters: {restricted_file_paths: [str]}
      max_file_path_length        -- parameters: {max_file_path_length: int}
      file_extension_restriction  -- parameters: {restricted_file_extensions: [str]}
      max_file_size               -- parameters: {max_file_size: int}  # in MiB
      workflows                   -- parameters: {workflows: [{repository_id, path, ref, sha?}],
                                                   do_not_enforce_on_create?}
      code_scanning               -- parameters: {code_scanning_tools: [{tool, security_alerts_threshold,
                                                                          alerts_threshold}]}

    operator values for pattern rules: starts_with | ends_with | contains | regex
    """

    type: str = Field(description="The type of rule")
    parameters: dict[str, Any] | None = Field(
        None,
        description="Parameters for the rule, if any. See GitHub docs for per-type parameters.",
    )


class Ruleset(BaseModel):
    name: str = Field(description="The name of the ruleset")
    target: RuleTarget = Field(
        default=RuleTarget.branch,
        description="The target of the ruleset: 'branch', 'tag', or 'push'",
    )
    enforcement: RuleEnforcement = Field(
        default=RuleEnforcement.active,
        description="The enforcement level: 'disabled', 'active', or 'evaluate'",
    )
    bypass_actors: list[BypassActor] | None = Field(
        None,
        description="Actors who can bypass this ruleset",
    )
    conditions: RulesetConditions | None = Field(
        None,
        description="Conditions specifying which refs the ruleset applies to",
    )
    rules: list[RulesetRule] | None = Field(
        None,
        description="The rules that make up the ruleset",
    )
    exists: OptBool = Field(True, description="Set to false to delete this ruleset")
