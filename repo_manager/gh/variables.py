import json
from typing import Any


from actions_toolkit import core as actions_toolkit

from github import GithubException
from github.Auth import AppInstallationAuth
from github.Repository import Repository

from repo_manager.utils import get_permissions
from repo_manager.schemas.secret import Secret


def __verify_variable_access__(repo: Repository) -> bool:
    """Verifies that the app has access to the secrets"""
    perms = get_permissions()
    if isinstance(repo._requester.auth, AppInstallationAuth) and perms.get("secrets", None) is None:
        raise GithubException(403, None, None, "App does not have access to secrets")
    return True


def __get_repo_variable_dict__(repo: Repository, path: str = "actions") -> dict[str, Any]:
    if path == "actions":
        return {variable.name: variable for variable in repo.get_variables()}
    else:
        return {variable.name: variable for variable in repo.get_environment(path).get_variables()}


def __update_variable__(repo: Repository, variable_name: str, value: str, path: str = "actions") -> bool:
    """
    :calls: `PATCH /repos/{owner}/{repo}/{path}/variables/{variable_name}
    <https://docs.github.com/en/rest/actions/variables?apiVersion=2022-11-28>`_

    :param variable_name: string
    :param value: string
    :path: string
    """
    put_parameters = {"name": variable_name, "value": value}
    status, headers, data = repo._requester.requestJson(
        "PATCH", f"{repo.url}/{path}/variables/{variable_name}", input=put_parameters
    )
    if status not in {204}:
        raise Exception(f"Unable to update variable: {variable_name}. Error: {json.loads(data)['message']}")
    return True


def diff_option(key: str, expected: Any, repo_value: Any) -> str | None:
    if expected is not None:
        if expected != repo_value:
            return f"{key} -- Expected: {expected} Found: {repo_value}"
    return None


def check_variables(repo: Repository, variables: list[Secret]) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Checks a repo's secrets vs our expected settings

    Args:
        repo (Repository): [description]
        secrets (List[Secret]): [description]

    Returns:
        Tuple[bool, Optional[List[str]]]: [description]
    """
    diffs = {}
    repo_dict = dict[str, Any]()
    if any(filter(lambda variable: variable.type == "actions", variables)):
        repo_dict.update(__get_repo_variable_dict__(repo))
    if any(filter(lambda variable: variable.type not in {"actions"}, variables)):
        first_variable = next(filter(lambda variable: variable.type not in {"actions"}, variables), None)
        if first_variable is not None:
            repo_dict.update(__get_repo_variable_dict__(repo, first_variable.type.replace("environments/", "")))
    config_dict = {variable.key: variable for variable in variables}
    repo_variable_names = {variable for variable in repo_dict.keys()}

    expected_variables_names = {variable.key for variable in filter(lambda variable: variable.exists, variables)}

    missing = list(expected_variables_names - repo_variable_names)
    if len(missing) > 0:
        diffs["missing"] = missing

    extra = list(
        repo_variable_names.intersection(
            {variable.key for variable in filter(lambda variable: variable.exists is False, variables)}
        )
    )
    if len(extra) > 0:
        diffs["extra"] = extra

    diff = {}
    variables_to_check_values_on = list(expected_variables_names.intersection(repo_variable_names))
    for variable_name in variables_to_check_values_on:
        config_var = config_dict.get(variable_name, None)
        repo_var = repo_dict.get(variable_name, None)
        if config_var.value != repo_var.value:
            diff[variable_name] = diff_option(variable_name, config_var.value, repo_var.value)

    if len(diff) > 0:
        diffs["diff"] = diff

    if len(diffs) > 0:
        return False, diffs

    return True, None


def update_variables(
    repo: Repository,
    variables: list[Secret],
    diffs: tuple[dict[str, list[str] | dict[str, Any]]],
) -> tuple[set[str], set[str]]:
    """Updates a repo's secrets to match the expected settings

    Args:
        repo (Repository): [description]
        variables (List[Secret]): [description]

    Returns:
        set[str]: [description]
    """
    errors = []
    variables_dict = {variable.key: variable for variable in variables}
    for issue_type in diffs.keys():
        if issue_type == "diff":
            variableNames = diffs[issue_type].keys()
        else:
            variableNames = diffs[issue_type]
        for variable in variableNames:
            if variables_dict[variable].exists:
                try:
                    if issue_type == "diff":
                        if variables_dict[variable].type == "actions":
                            __update_variable__(repo, variable, variables_dict[variable].value)
                        else:
                            __update_variable__(
                                repo,
                                variable,
                                variables_dict[variable].value,
                                variables_dict[variable].type,
                            )
                        actions_toolkit.info(f"Updated variable {variable}")
                    else:
                        if variables_dict[variable].type == "actions":
                            repo.create_variable(variable, variables_dict[variable].value)
                        else:
                            try:
                                repo.get_environment(
                                    variables_dict[variable].type.replace("environments/", "")
                                ).create_variable(variable, variables_dict[variable].value)
                            except GithubException as exc:
                                if exc.status in [409, 422]:
                                    __update_variable__(
                                        repo,
                                        variable,
                                        variables_dict[variable].value,
                                        variables_dict[variable].type,
                                    )
                        actions_toolkit.info(f"Created variable {variable}")
                except Exception as exc:  # this should be tighter
                    if variables_dict[variable].required:
                        errors.append(
                            {
                                "type": "variable-update",
                                "key": variable.key,
                                "error": f"{exc}",
                            }
                        )
            else:
                try:
                    if variables_dict[variable].type == "actions":
                        repo.delete_variable(variable)
                    else:
                        repo.get_environment(
                            variables_dict[variable].type.replace("environments/", "")
                        ).delete_variable(variable)
                    actions_toolkit.info(f"Deleted variable {variable}")
                except Exception as exc:  # this should be tighter
                    errors.append(
                        {
                            "type": "variable-update",
                            "key": variable.key,
                            "error": f"{exc}",
                        }
                    )
    return errors, []
