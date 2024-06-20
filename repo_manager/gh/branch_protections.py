from copy import deepcopy
from typing import Any

from actions_toolkit import core as actions_toolkit

from github.Consts import mediaTypeRequireMultipleApprovingReviews
from github.GithubException import GithubException
from github.GithubObject import NotSet
from github.Repository import Repository

from repo_manager.schemas.branch_protection import BranchProtection
from repo_manager.schemas.branch_protection import ProtectionOptions
from repo_manager.utils import attr_to_kwarg
from repo_manager.utils import objary_to_list


def __diff_option__(key: str, expected: Any, repo_value: Any) -> str | None:
    if expected is not None:
        if expected != repo_value:
            return f"{key} -- Expected: {expected} Found: {repo_value}"
    return None


def __update_branch_protection__(repo: Repository, branch: str, protection_config: ProtectionOptions):  # noqa: C901
    # Copied from https://github.com/PyGithub/PyGithub/blob/001970d4a828017f704f6744a5775b4207a6523c/github/Branch.py#L112
    # Until pygithub supports this, we need to do it manually
    def edit_protection(  # nosec
        branch,
        required_status_checks=NotSet,
        enforce_admins=NotSet,
        dismissal_users=NotSet,
        dismissal_teams=NotSet,
        dismiss_stale_reviews=NotSet,
        require_code_owner_reviews=NotSet,
        required_approving_review_count=NotSet,
        user_push_restrictions=NotSet,
        team_push_restrictions=NotSet,
        user_bypass_pull_request_allowances=NotSet,
        team_bypass_pull_request_allowances=NotSet,
        required_linear_history=NotSet,
        allow_force_pushes=NotSet,
        allow_deletions=NotSet,
        block_creations=NotSet,
        required_conversation_resolution=NotSet,
    ):  # nosec
        """
        :calls: `PUT /repos/{owner}/{repo}/branches/{branch}/protection <https://docs.github.com/en/rest/branches/branch-protection?apiVersion=2022-11-28#update-branch-protection>`_
        :required_status_checks: dict
        :enforce_admins: bool
        :dismissal_users: list of strings
        :dismissal_teams: list of strings
        :dismiss_stale_reviews: bool
        :require_code_owner_reviews: bool
        :required_approving_review_count: int
        :user_push_restrictions: list of strings
        :team_push_restrictions: list of strings
        :user_bypass_pull_request_allowances: list of strings
        :team_bypass_pull_request_allowances: list of strings
        NOTE: The GitHub API groups strict and contexts together, both must
        be submitted. Take care to pass both as arguments even if only one is
        changing. Use edit_required_status_checks() to avoid this.
        """
        assert required_status_checks is NotSet or isinstance(required_status_checks, dict), required_status_checks  # nosec assert_used
        assert enforce_admins is NotSet or isinstance(enforce_admins, bool), enforce_admins  # nosec assert_used
        assert dismissal_users is NotSet or all(  # nosec assert_used
            isinstance(element, str) for element in dismissal_users
        ), dismissal_users
        assert dismissal_teams is NotSet or all(  # nosec assert_used
            isinstance(element, str) for element in dismissal_teams
        ), dismissal_teams
        assert dismiss_stale_reviews is NotSet or isinstance(dismiss_stale_reviews, bool), dismiss_stale_reviews  # nosec assert_used
        assert require_code_owner_reviews is NotSet or isinstance(  # nosec assert_used
            require_code_owner_reviews, bool
        ), require_code_owner_reviews
        assert required_approving_review_count is NotSet or isinstance(  # nosec assert_used
            required_approving_review_count, int
        ), required_approving_review_count

        post_parameters = {}
        if required_status_checks is not NotSet:
            post_parameters["required_status_checks"] = required_status_checks
        else:
            post_parameters["required_status_checks"] = {
                "strict": False,
                "contexts": [],
            }

        if enforce_admins is not NotSet:
            post_parameters["enforce_admins"] = enforce_admins
        else:
            post_parameters["enforce_admins"] = None

        if (
            dismissal_users is not NotSet
            or dismissal_teams is not NotSet
            or dismiss_stale_reviews is not NotSet
            or require_code_owner_reviews is not NotSet
            or required_approving_review_count is not NotSet
            or user_bypass_pull_request_allowances is not NotSet
            or team_bypass_pull_request_allowances is not NotSet
        ):
            post_parameters["required_pull_request_reviews"] = {}
            if dismiss_stale_reviews is not NotSet:
                post_parameters["required_pull_request_reviews"]["dismiss_stale_reviews"] = dismiss_stale_reviews
            if require_code_owner_reviews is not NotSet:
                post_parameters["required_pull_request_reviews"]["require_code_owner_reviews"] = (
                    require_code_owner_reviews
                )
            if required_approving_review_count is not NotSet:
                post_parameters["required_pull_request_reviews"]["required_approving_review_count"] = (
                    required_approving_review_count
                )
            if dismissal_users is not NotSet or dismissal_teams is not NotSet:
                if dismissal_users is NotSet:
                    dismissal_teams = []
                if dismissal_teams is NotSet:
                    dismissal_teams = []
                post_parameters["required_pull_request_reviews"]["dismissal_restrictions"] = {
                    "users": dismissal_users,
                    "teams": dismissal_teams,
                }
            if user_bypass_pull_request_allowances is not NotSet or team_bypass_pull_request_allowances is not NotSet:
                if user_bypass_pull_request_allowances is NotSet:
                    user_bypass_pull_request_allowances = []
                if team_bypass_pull_request_allowances is NotSet:
                    team_bypass_pull_request_allowances = []
                post_parameters["required_pull_request_reviews"]["bypass_pull_request_allowances"] = {
                    "users": user_bypass_pull_request_allowances,
                    "teams": team_bypass_pull_request_allowances,
                }
        else:
            post_parameters["required_pull_request_reviews"] = None

        if user_push_restrictions is not NotSet or team_push_restrictions is not NotSet:
            if user_push_restrictions is NotSet:
                user_push_restrictions = []
            if team_push_restrictions is NotSet:
                team_push_restrictions = []
            post_parameters["restrictions"] = {
                "users": user_push_restrictions,
                "teams": team_push_restrictions,
            }
        else:
            post_parameters["restrictions"] = None

        if required_linear_history is not NotSet:
            post_parameters["required_linear_history"] = required_linear_history
        else:
            post_parameters["required_linear_history"] = None

        if allow_force_pushes is not NotSet:
            post_parameters["allow_force_pushes"] = allow_force_pushes
        else:
            post_parameters["allow_force_pushes"] = None

        if allow_deletions is not NotSet:
            post_parameters["allow_deletions"] = allow_deletions
        else:
            post_parameters["allow_deletions"] = None

        if block_creations is not NotSet:
            post_parameters["block_creations"] = block_creations
        else:
            post_parameters["block_creations"] = None

        if required_conversation_resolution is not NotSet:
            post_parameters["required_conversation_resolution"] = required_conversation_resolution
        else:
            post_parameters["required_conversation_resolution"] = None

        headers, data = branch._requester.requestJsonAndCheck(
            "PUT",
            branch.protection_url,
            headers={"Accept": mediaTypeRequireMultipleApprovingReviews},
            input=post_parameters,
        )

    this_branch = repo.get_branch(branch)
    kwargs = {}
    status_check_kwargs = {}
    extra_kwargs = {}

    if protection_config.pr_options is not None:
        attr_to_kwarg("required_approving_review_count", protection_config.pr_options, kwargs)
        attr_to_kwarg("dismiss_stale_reviews", protection_config.pr_options, kwargs)
        attr_to_kwarg("require_code_owner_reviews", protection_config.pr_options, kwargs)

        if repo.organization is not None:
            attr_to_kwarg(
                "users",
                protection_config.pr_options.dismissal_restrictions,
                kwargs,
                transform_key="dismissal_users",
            )
            attr_to_kwarg(
                "teams",
                protection_config.pr_options.dismissal_restrictions,
                kwargs,
                transform_key="dismissal_teams",
            )
            attr_to_kwarg(
                "users",
                protection_config.pr_options.dismissal_restrictions,
                kwargs,
                transform_key="user_bypass_pull_request_allowances",
            )
            attr_to_kwarg(
                "teams",
                protection_config.pr_options.dismissal_restrictions,
                kwargs,
                transform_key="team_bypass_pull_request_allowances",
            )

    if repo.organization is not None:
        attr_to_kwarg(
            "users",
            protection_config.restrictions,
            kwargs,
            transform_key="user_push_restrictions",
        )
        attr_to_kwarg(
            "teams",
            protection_config.restrictions,
            kwargs,
            transform_key="team_push_restrictions",
        )

    attr_to_kwarg("enforce_admins", protection_config, kwargs)

    # these are going to be used by edit_required_status_checks
    attr_to_kwarg("strict", protection_config.required_status_checks, status_check_kwargs)
    if protection_config.required_status_checks.checks is None:
        status_check_kwargs["contexts"] = []
    else:
        attr_to_kwarg(
            "checks",
            protection_config.required_status_checks,
            status_check_kwargs,
            transform_key="contexts",
        )
    extra_kwargs["required_status_checks"] = status_check_kwargs

    # these are not handled by edit_protection, so we have to use the custom api
    attr_to_kwarg(
        "require_linear_history",
        protection_config,
        extra_kwargs,
        transform_key="required_linear_history",
    )
    attr_to_kwarg("allow_force_pushes", protection_config, extra_kwargs)
    attr_to_kwarg("allow_deletions", protection_config, extra_kwargs)
    attr_to_kwarg("block_creations", protection_config, extra_kwargs)
    attr_to_kwarg(
        "require_conversation_resolution",
        protection_config,
        extra_kwargs,
        transform_key="required_conversation_resolution",
    )

    try:
        edit_protection(branch=this_branch, **kwargs, **extra_kwargs)
    except GithubException as exc:
        raise ValueError(f"{exc.data['message']} {exc.data['documentation_url']}")
    # This errors out because the underlying method does a UPDATE instead of a POST as stated by GitHub documentation
    # was able to fix this issue by adding the additional key to kwargs above; signed commits could maybe be done too..
    # if status_check_kwargs != {}:
    #     try:
    #         this_branch.edit_required_status_checks(**status_check_kwargs)
    #     except GithubException as exc:
    #         raise ValueError(f"{exc.data['message']} {exc.data['documentation_url']}")

    # signed commits has its own method
    if protection_config.require_signed_commits is not None:
        if protection_config.require_signed_commits:
            this_branch.add_required_signatures()
        else:
            this_branch.remove_required_signatures()


def check_repo_branch_protections(
    repo: Repository, config_branch_protections: list[BranchProtection]
) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Checks a repo's branch protections vs our expected settings

    Args:
        repo (Repository): [description]
        secrets (List[Secret]): [description]

    """
    repo_branches = {branch.name: branch for branch in repo.get_branches()}

    missing_protections = []
    extra_protections = []
    diff_protections = {}

    for config_bp in config_branch_protections:
        repo_bp = repo_branches.get(config_bp.name, None)
        if repo_bp is None and config_bp.exists:
            # This should maybe be a regex pattern?
            raise RuntimeError(f"Branch {config_bp.name} does not exist in repo {repo.full_name}")
        if not repo_bp.protected and config_bp.exists:
            missing_protections.append(config_bp.name)
            continue
        if not config_bp.exists and repo_bp.protected:
            extra_protections.append(config_bp.name)
            continue

        diffs = {}
        if config_bp.protection is None:
            continue

        try:
            this_protection = repo_bp.get_protection()
        except Exception as exc:
            actions_toolkit.info(f"Repo {repo.full_name} does not currently have any branch protections defined?")
            actions_toolkit.info(f"error: {exc}")
            continue
        if config_bp.protection.pr_options is not None:
            if (
                config_bp.protection.pr_options.required_approving_review_count is not None
                and this_protection.required_pull_request_reviews.required_approving_review_count
                != config_bp.protection.pr_options.required_approving_review_count
            ):
                diffs["required_approving_review_count"] = {
                    "expected": config_bp.protection.pr_options.required_approving_review_count,
                    "found": None
                    if (this_protection.required_pull_request_reviews is None)
                    else this_protection.required_pull_request_reviews.required_approving_review_count,
                }
            if (
                config_bp.protection.pr_options.dismiss_stale_reviews is not None
                and this_protection.required_pull_request_reviews.dismiss_stale_reviews
                != config_bp.protection.pr_options.dismiss_stale_reviews
            ):
                diffs["dismiss_stale_reviews"] = {
                    "expected": config_bp.protection.pr_options.dismiss_stale_reviews,
                    "found": None
                    if (this_protection.required_pull_request_reviews is None)
                    else this_protection.required_pull_request_reviews.dismiss_stale_reviews,
                }
            if (
                config_bp.protection.pr_options.require_code_owner_reviews is not None
                and this_protection.required_pull_request_reviews.require_code_owner_reviews
                != config_bp.protection.pr_options.require_code_owner_reviews
            ):
                diffs["require_code_owner_reviews"] = {
                    "expected": config_bp.protection.pr_options.require_code_owner_reviews,
                    "found": None
                    if (this_protection.required_pull_request_reviews is None)
                    else this_protection.required_pull_request_reviews.require_code_owner_reviews,
                }
            # for now, not checking dismissal options. Will note that in the docs

        if (
            config_bp.protection.required_status_checks is not None
            and this_protection.required_status_checks is not None
        ):
            if (
                config_bp.protection.required_status_checks.strict is not None
                and config_bp.protection.required_status_checks.strict != this_protection.required_status_checks.strict
            ):
                diffs["required_status_checks::strict"] = {
                    "expected": config_bp.protection.required_status_checks.strict,
                    "found": this_protection.required_status_checks.strict,
                }
            # Without sorting, they sometimes get flagged as different just due to the ordinality of them
            if config_bp.protection.required_status_checks.checks is not None:
                config_bp.protection.required_status_checks.checks.sort()
            if this_protection.required_status_checks.contexts is not None:
                this_protection.required_status_checks.contexts.sort()
            if (
                config_bp.protection.required_status_checks.checks is not None
                and config_bp.protection.required_status_checks.checks
                != this_protection.required_status_checks.contexts
            ):
                diffs["required_status_checks::checks"] = {
                    "expected": config_bp.protection.required_status_checks.checks,
                    "found": this_protection.required_status_checks.contexts,
                }

        if (config_bp.protection.enforce_admins or this_protection.enforce_admins) != this_protection.enforce_admins:
            diffs["enforce_admins"] = {
                "expected": config_bp.protection.enforce_admins,
                "found": this_protection.enforce_admins,
            }
        if config_bp.protection.require_linear_history is not None and config_bp.protection.require_linear_history != (
            this_protection.required_linear_history or ""
        ):
            diffs["require_linear_history"] = {
                "expected": config_bp.protection.require_linear_history,
                "found": this_protection.required_linear_history,
            }
        if config_bp.protection.allow_force_pushes is not None and config_bp.protection.allow_force_pushes != (
            this_protection.allow_force_pushes or ""
        ):
            diffs["allow_force_pushes"] = {
                "expected": config_bp.protection.allow_force_pushes,
                "found": this_protection.allow_force_pushes,
            }
        if config_bp.protection.allow_deletions is not None and config_bp.protection.allow_deletions != (
            this_protection.allow_deletions or ""
        ):
            diffs["allow_deletions"] = {
                "expected": config_bp.protection.allow_deletions,
                "found": this_protection.allow_deletions,
            }
        # block_creations missing? Not sure if it is supported by the pygithub library
        if (
            config_bp.protection.require_conversation_resolution is not None
            and config_bp.protection.require_conversation_resolution
            != (this_protection.required_conversation_resolution or "")
        ):
            diffs["require_conversation_resolution"] = {
                "expected": config_bp.protection.require_conversation_resolution,
                "found": this_protection.required_conversation_resolution,
            }
        # require_signed_commits missing? Not sure if it is supported by the pygithub library

        if this_protection.required_pull_request_reviews is None:
            dismissal_users = []
            dismissal_teams = []
        else:
            if this_protection.required_pull_request_reviews.dismissal_teams is not None:
                dismissal_teams = objary_to_list("slug", this_protection.required_pull_request_reviews.dismissal_teams)
            else:
                dismissal_teams = []

            if this_protection.required_pull_request_reviews.dismissal_users is not None:
                dismissal_users = objary_to_list("name", this_protection.required_pull_request_reviews.dismissal_users)
            else:
                dismissal_users = []

        if config_bp.protection.pr_options is not None:
            dismissal_users.sort()
            if config_bp.protection.pr_options.dismissal_restrictions is not None:
                if config_bp.protection.pr_options.dismissal_restrictions.teams is not None:
                    config_bp.protection.pr_options.dismissal_restrictions.teams.sort()
                if (
                    config_bp.protection.pr_options.dismissal_restrictions.users is not None
                    and config_bp.protection.pr_options.dismissal_restrictions.users != (dismissal_users or [])
                ):
                    diffs["dismissal_users"] = {
                        "expected": config_bp.protection.pr_options.dismissal_restrictions.users,
                        "found": dismissal_users,
                    }

            dismissal_teams.sort()
            if config_bp.protection.pr_options.dismissal_restrictions is not None:
                if config_bp.protection.pr_options.dismissal_restrictions.teams is not None:
                    config_bp.protection.pr_options.dismissal_restrictions.teams.sort()
                if (
                    config_bp.protection.pr_options.dismissal_restrictions.teams is not None
                    and config_bp.protection.pr_options.dismissal_restrictions.teams != (dismissal_teams or [])
                ):
                    diffs["dismissal_teams"] = {
                        "expected": config_bp.protection.pr_options.dismissal_restrictions.teams,
                        "found": dismissal_teams,
                    }

        # diffs = [i for i in diffs if i is not None] # Why was this here?
        if len(diffs) > 0:
            diff_protections[config_bp.name] = deepcopy(diffs)

    diffs = {}
    if len(missing_protections) > 0:
        diffs["missing"] = missing_protections

    if len(extra_protections) > 0:
        diffs["extra"] = extra_protections

    if len(diff_protections) > 0:
        diffs["diff"] = diff_protections

    if len(diffs) > 0:
        return False, diffs

    return True, None


def update_branch_protections(
    repo: Repository,
    config_branch_protections: list[BranchProtection],
    diffs: tuple[dict[str, list[str] | dict[str, Any]]],
) -> tuple[set[str], set[str]]:
    """Updates a repo's branch protection policies to match the expected settings

    Args:
        repo (Repository): [description]
        secrets (List[Secret]): [description]

    Returns:
        set[str]: [description]
    """
    errors = []
    branch_protections_dict = {bp.name: bp for bp in config_branch_protections}
    for issue_type in diffs.keys():
        branches = diffs[issue_type] if issue_type != "diff" else diffs[issue_type].keys()
        for branch_name in branches:
            try:
                if issue_type == "extra":
                    # remove branch protection
                    this_branch = repo.get_branch(branch_name)
                    this_branch.remove_protection()
                else:
                    # update or create branch protection
                    bp_config = branch_protections_dict[branch_name]
                    if bp_config.protection is not None:
                        __update_branch_protection__(repo, branch_name, bp_config.protection)
                        actions_toolkit.info(f"Updated branch proection for {branch_name}")
                    else:
                        actions_toolkit.warning(f"Branch protection config for {branch_name} is empty")
            except GithubException as ghexc:
                if ghexc.status == 403:
                    actions_toolkit.warning(f"Unable to modify branch protection for {branch_name}.  {ghexc.message}")
                if ghexc.status == 404:
                    actions_toolkit.set_failed(
                        f"Can't change branch protection for {branch_name} because either the branch or the protection does not exist"
                    )
                if ghexc.status not in [403, 404]:
                    # a 404 on a delete is fine, means it isnt protected
                    errors.append(
                        {
                            "type": "bp-delete" if issue_type == "extra" else "bp-update",
                            "name": branch_name,
                            "error": f"{ghexc}",
                        }
                    )
            except Exception as exc:  # this should be tighter
                errors.append({"type": "bp-delete", "name": branch_name, "error": f"{exc}"})

    return errors, []
