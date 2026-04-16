import sys
import json
import requests

from actions_toolkit import core as actions_toolkit
from actions_toolkit.file_command import issue_file_command

from github.GithubException import GithubException

from pydantic import ValidationError

from yaml import YAMLError


from repo_manager.utils import get_inputs
from repo_manager.utils.markdown import generate
from repo_manager.schemas import load_config
from repo_manager.gh.settings import check_repo_settings, update_settings
from repo_manager.gh.labels import check_repo_labels, update_labels
from repo_manager.gh.collaborators import check_collaborators, update_collaborators
from repo_manager.gh.branch_protections import check_repo_branch_protections, update_branch_protections
from repo_manager.gh.secrets import check_repo_secrets, update_secrets
from repo_manager.gh.variables import check_variables, update_variables
from repo_manager.gh.environments import check_repo_environments, update_environments
from repo_manager.gh.files import check_files, update_files

# Maps each settings category to its required GitHub App permission, PAT scope,
# and a representative API endpoint to probe when a 403 is encountered.
REQUIRED_PERMISSIONS = {
    "settings": {
        "app_permission": "administration: write",
        "pat_scope": "repo",
        "description": "Repository settings (description, merge strategies, branch defaults, security alerts, etc.)",
        "probe_path": "",  # GET /repos/{owner}/{repo}
    },
    "collaborators": {
        "app_permission": "members: write (org repos) / administration: write (user repos)",
        "pat_scope": "repo",
        "description": "Collaborator and team access management",
        "probe_path": "/collaborators",
    },
    "labels": {
        "app_permission": "issues: write",
        "pat_scope": "repo",
        "description": "Issue and pull-request labels",
        "probe_path": "/labels",
    },
    "branch_protections": {
        "app_permission": "administration: write",
        "pat_scope": "repo",
        "description": "Branch protection rules",
        "probe_path": "/branches",
    },
    "secrets": {
        "app_permission": "secrets: write",
        "pat_scope": "repo",
        "description": "Actions secrets (repo-level)",
        "probe_path": "/actions/secrets",
    },
    "secrets_dependabot": {
        "app_permission": "dependabot_secrets: write",
        "pat_scope": "repo, admin:org",
        "description": "Dependabot secrets",
        "probe_path": "/dependabot/secrets",
    },
    "variables": {
        "app_permission": "variables: write",
        "pat_scope": "repo",
        "description": "Actions variables",
        "probe_path": "/actions/variables",
    },
    "environments": {
        "app_permission": "environments: write, actions: read",
        "pat_scope": "repo",
        "description": "Deployment environments (including environment secrets and variables)",
        "probe_path": "/environments",
    },
    "files": {
        "app_permission": "contents: write, pull_requests: write",
        "pat_scope": "repo",
        "description": "File copy/move/delete operations and pull-request creation",
        "probe_path": "/contents",
    },
}


def _debug_probe_endpoint(category: str, repo_full_name: str, token: str, api_url: str = "https://api.github.com") -> None:
    """Probe a representative endpoint for a category and log what permissions GitHub says are required."""
    probe_path = REQUIRED_PERMISSIONS.get(category, {}).get("probe_path")
    if probe_path is None:
        return
    url = f"{api_url}/repos/{repo_full_name}{probe_path}"
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        actions_toolkit.debug(
            f"Permission probe [{category}] GET {url}: "
            f"status={resp.status_code} "
            f"x-accepted-github-permissions={resp.headers.get('x-accepted-github-permissions')} "
            f"x-oauth-scopes={resp.headers.get('x-oauth-scopes')} "
            f"body={resp.text[:300]}"
        )
    except Exception as probe_exc:
        actions_toolkit.debug(f"Permission probe [{category}] failed: {probe_exc}")


def _format_permission_warning(category: str, exc: Exception) -> str:
    """Build a human-readable warning message for a permission error."""
    info = REQUIRED_PERMISSIONS.get(category, {})
    lines = [
        f"⚠️  Insufficient permissions to manage **{category}** — skipping.",
        f"   Error: {exc}",
    ]
    if info:
        lines += [
            f"   Scope/feature: {info.get('description', '')}",
            f"   Required GitHub App permission: `{info.get('app_permission', 'unknown')}`",
            f"   Required PAT scope: `{info.get('pat_scope', 'unknown')}`",
            "   Add the missing permission to your GitHub App or Personal Access Token and re-run.",
        ]
    return "\n".join(lines)


def _is_permission_error(exc: Exception) -> bool:
    """Return True when an exception represents a 401/403 authorization failure."""
    if isinstance(exc, GithubException) and exc.status in (401, 403):
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in ("403", "401", "forbidden", "not have access", "resource not accessible"))


def main():  # noqa: C901
    try:
        inputs = get_inputs()
    # actions toolkit has very broad exceptions :(
    except Exception as exc:
        actions_toolkit.set_failed(f"Unable to collect inputs {exc}")
    actions_toolkit.debug(f"Loading config from {inputs['settings_file']}")
    try:
        config = load_config(inputs["settings_file"])
    except FileNotFoundError:
        actions_toolkit.set_failed(f"{inputs['settings_file']} does not exist or is not readable")
    except YAMLError as exc:
        actions_toolkit.set_failed(f"Unable to read {inputs['settings_file']} - {exc}")
    except ValidationError as exc:
        actions_toolkit.set_failed(f"{inputs['settings_file']} is invalid - {exc}")

    actions_toolkit.debug(f"Inputs: {inputs}")
    try:
        from repo_manager.utils import get_client, get_permissions
        get_client()
        actions_toolkit.debug(f"App installation permissions: {get_permissions()}")
    except Exception as exc:
        actions_toolkit.debug(f"Could not retrieve installation permissions for debug: {exc}")
    if inputs["action"] == "validate":
        actions_toolkit.set_output("result", f"Validated {inputs['settings_file']}")
        actions_toolkit.debug(json_diff := json.dumps({}))
        actions_toolkit.set_output("diff", json_diff)
        sys.exit(0)
    actions_toolkit.info(f"Config from {inputs['settings_file']} validated.")

    check_result = True
    diffs = {}
    permission_warnings = []
    for check, to_check in {
        check_repo_settings: ("settings", config.settings),
        check_collaborators: ("collaborators", config.collaborators),
        check_repo_labels: ("labels", config.labels),
        check_repo_branch_protections: (
            "branch_protections",
            config.branch_protections,
        ),
        check_repo_secrets: ("secrets", config.secrets),
        check_variables: ("variables", config.variables),
        check_repo_environments: ("environments", config.environments),
        check_files: ("files", config.batch_file_operations),
    }.items():
        check_name, to_check = to_check
        if to_check is not None:
            try:
                this_check, this_diffs = check(inputs["repo_object"], to_check)
                check_result &= this_check
                if this_diffs is not None:
                    diffs[check_name] = this_diffs
            except GithubException as exc:
                if exc.status in (401, 403):
                    warning_msg = _format_permission_warning(check_name, exc)
                    actions_toolkit.warning(warning_msg)
                    permission_warnings.append(warning_msg)
                    _token = inputs.get("token")
                    _repo = inputs.get("repo_object")
                    _api_url = inputs.get("github_server_url", "https://api.github.com")
                    if _token and _repo:
                        _debug_probe_endpoint(check_name, _repo.full_name, _token, _api_url)
                else:
                    raise

    actions_toolkit.debug(json_diff := json.dumps(diffs))
    actions_toolkit.set_output("diff", json_diff)

    def _permission_warnings_section() -> str:
        if not permission_warnings:
            return ""
        lines = ["## ⚠️ Permission Warnings", ""]
        lines += ["> " + line for w in permission_warnings for line in w.splitlines()]
        lines.append("")
        return "\n".join(lines)

    if inputs["action"] == "check":
        if not check_result:
            summary = _permission_warnings_section() + generate(diffs, {"open": "Differences found"})
            issue_file_command("STEP_SUMMARY", summary)
            if inputs["fail_on_diff"] == "true":
                actions_toolkit.set_output("result", "Check failed, diff detected")
                actions_toolkit.set_failed("Diff detected")
            else:
                actions_toolkit.warning("Diff detected")
        else:
            summary = _permission_warnings_section() or "# No changes detected"
            issue_file_command("STEP_SUMMARY", summary)
        actions_toolkit.set_output("result", "Check passed")
        sys.exit(0)

    if inputs["action"] == "apply":
        errors = []
        messages = {"open": "Changes applied"}
        for update, to_update in {
            update_settings: ("settings", config.settings, diffs.get("settings", None)),
            update_collaborators: ("collaborators", config.collaborators, diffs.get("collaborators", None)),
            update_labels: ("labels", config.labels, diffs.get("labels", None)),
            update_branch_protections: (
                "branch_protections",
                config.branch_protections,
                diffs.get("branch_protections", None),
            ),
            update_secrets: ("secrets", config.secrets, diffs.get("secrets", None)),
            update_variables: ("variables", config.variables, diffs.get("variables", None)),
            update_environments: ("environments", config.environments, diffs.get("environments", None)),
            update_files: ("files", config.batch_file_operations, diffs.get("files", None)),
        }.items():
            update_name, to_update, categorical_diffs = to_update
            if categorical_diffs is not None:
                try:
                    application_errors, application_summary = update(
                        inputs["repo_object"], to_update, categorical_diffs
                    )
                    if len(application_errors) > 0:
                        errors.append(application_errors)
                    if len(application_summary) > 0:
                        messages[update_name] = application_summary
                    else:
                        actions_toolkit.info(f"Synced {update_name}")
                except Exception as exc:
                    if _is_permission_error(exc):
                        warning_msg = _format_permission_warning(update_name, exc)
                        actions_toolkit.warning(warning_msg)
                        permission_warnings.append(warning_msg)
                    else:
                        errors.append({"type": f"{update_name}-update", "error": f"{exc}"})

        perm_section = _permission_warnings_section()
        if perm_section and len(messages) > 1:
            issue_file_command("STEP_SUMMARY", perm_section + generate(diffs, messages))
        elif len(messages) > 1:
            issue_file_command("STEP_SUMMARY", generate(diffs, messages))
        elif perm_section:
            issue_file_command("STEP_SUMMARY", perm_section)

        if len(errors) > 0:
            actions_toolkit.error(json.dumps(errors))
            actions_toolkit.set_failed("Errors during apply")
        actions_toolkit.set_output("result", "Apply successful")


if __name__ == "__main__":
    main()
