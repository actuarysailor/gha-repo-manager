import os
from typing import Any
import requests

from actions_toolkit import core as actions_toolkit

from github import Github, Repository, Organization, Requester
from github.Auth import AppInstallationAuth, Token

# Needed to handle extracting certain attributes/fields from nested objects and lists
from itertools import repeat

from repo_manager.gh import get_github_client

from ._inputs import INPUTS

VALID_ACTIONS = {"validate": None, "check": None, "apply": None}


def __get_inputs__() -> dict:
    """Get inputs from our workflow, valudate them, and return as a dict
    Reads inputs from the dict INPUTS. This dict is generated from the actions.yml file.
    Non required inputs that are not set are returned as None
    Returns:
        Dict[str, Any]: [description]
    """
    global kwargs
    kwargs = dict()
    for input_name, input_config in INPUTS.items():
        if input_config.get("multiline", False):
            this_input_value = "\n".join(
                actions_toolkit.get_multiline_input(
                    input_name,
                    required=input_config.get("required", False),
                )
            )
        else:
            this_input_value = actions_toolkit.get_input(
                input_name,
                required=input_config.get("required", False),
            )
        kwargs[input_name] = this_input_value if this_input_value != "" else None
        # use a .env file to set defaults for local testing
        # https://docs.github.com/en/actions/learn-github-actions/environment-variables
        # if (
        #     os.environ.get("CI", "false").lower() == "false"
        #     and os.environ.get("GITHUB_ACTIONS", "false").lower() == "false"
        # ):
        #     if kwargs[input_name] is None:
        #         kwargs[input_name] = input_config.get("default", None)
        #         if kwargs[input_name] is None:
        #             actions_toolkit.set_failed(f"Error getting inputs. {input_name} is missing a default")
    # Backward compat: if target is not set but repo is, use repo as target (deprecated)
    if not kwargs.get("target") and kwargs.get("repo"):
        actions_toolkit.warning("Input 'repo' is deprecated. Please use 'target' instead.")
        kwargs["target"] = kwargs["repo"]
    # Fall back to "self" if neither target nor repo was provided
    if not kwargs.get("target"):
        kwargs["target"] = "self"
    kwargs["owner"] = (
        kwargs["target"].split("/")[0]
        if kwargs["target"] not in (None, "", "self")
        else os.environ.get("GITHUB_REPOSITORY_OWNER", None)
    )
    # scope is resolved fully in validate_inputs; nothing to pre-compute here
    return kwargs


# inputs["app_id"], inputs["private_key"], inputs.get("owner", None), inputs.get("repo", None)


def __get_api_url__() -> str:
    global kwargs  # this never gets added to the dictionary
    kwargs = __get_inputs__() if "kwargs" not in globals() else kwargs
    global api_url
    if kwargs["github_server_url"] == "https://github.com":
        api_url = "https://api.github.com"
    else:
        api_url = kwargs["github_server_url"] + "/api/v3"
    actions_toolkit.debug(f"api_url: {api_url}")
    return api_url


def __get_token__() -> str:
    global kwargs


def __get_token_permissions__(requester: Requester) -> dict:
    headers = {
        "Authorization": f"Bearer {requester.auth.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.get(requester.base_url, headers=headers, timeout=10)
    actions_toolkit.debug(f"response: {response}")
    # response.headers.get('X-Accepted-GitHub-Permissions')
    return {}


def get_client() -> Github:
    global client
    if "client" in globals():
        return client
    global kwargs
    kwargs = __get_inputs__() if "kwargs" not in globals() else kwargs
    global api_url
    api_url = __get_api_url__() if "api_url" not in globals() else api_url
    try:
        global permissions
        client, permissions, repo_selection = get_github_client(api_url, **kwargs)
        actions_toolkit.debug(f"App installation repository_selection: {repo_selection}")
        if isinstance(client._Github__requester.auth, AppInstallationAuth):
            kwargs["username"] = "x-access-token"
            kwargs["token"] = client._Github__requester.auth.token
        elif isinstance(client._Github__requester.auth, Token):
            kwargs["username"] = os.environ.get("GITHUB_ACTOR", None)
            permissions = __get_token_permissions__(client._Github__requester)
        else:
            raise ValueError("Unknown authentication method")
    except Exception as exc:  # this should be tighter
        actions_toolkit.set_failed(f"Error while retrieving GitHub REST API Client from {api_url}. {exc}")
    actions_toolkit.debug(f"permissions: {permissions}")
    return client


def get_repo() -> Repository:
    global kwargs
    if kwargs.get("repo_object", None) is not None:
        return kwargs["repo_object"]
    kwargs = __get_inputs__() if "kwargs" not in globals() else kwargs
    global client
    client = get_client() if "client" not in globals() else client
    try:
        repo = client.get_repo(kwargs["target"])
    except Exception as exc:  # this should be tighter
        actions_toolkit.set_failed(f"Error while retrieving {kwargs['target']} from Github. {exc}")
    return repo


def get_organization() -> Organization:
    global kwargs
    kwargs = __get_inputs__() if "kwargs" not in globals() else kwargs
    global client
    client = get_client() if "client" not in globals() else client
    try:
        org = client.get_organization(kwargs["target"].split("/")[0])
    except Exception as exc:  # this should be tighter
        actions_toolkit.set_failed(f"Error while retrieving {kwargs['target'].split('/')[0]} from Github. {exc}")
    return org


def get_org_by_name(org_login: str) -> Organization:
    """Fetch a GitHub Organization object by its login name."""
    global client
    client = get_client() if "client" not in globals() else client
    try:
        return client.get_organization(org_login)
    except Exception as exc:
        actions_toolkit.set_failed(f"Error while retrieving org '{org_login}' from Github. {exc}")


def get_permissions() -> set[str]:
    if "permissions" not in globals():
        raise ValueError("Permissions not set. Please run get_client() first")
    return permissions


def get_inputs() -> dict[str, Any]:
    """Get inputs from our workflow, valudate them, and return as a dict
    Reads inputs from the dict INPUTS. This dict is generated from the actions.yml file.
    Non required inputs that are not set are returned as None
    Returns:
        Dict[str, Any]: [description]
    """
    global kwargs
    kwargs = __get_inputs__() if "kwargs" not in globals() else kwargs
    return validate_inputs(kwargs)


def validate_inputs(parsed_inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate inputs
    Args:
        inputs (Dict[str, Any]): [description]
    """
    if parsed_inputs["action"] not in VALID_ACTIONS:
        actions_toolkit.set_failed(f"Invalid action: {parsed_inputs['action']}")
    # validate our inputs
    parsed_inputs["action"] = parsed_inputs["action"].lower()
    if parsed_inputs["action"] not in VALID_ACTIONS.keys():
        actions_toolkit.set_failed(
            f"Error while loading RepoManager Config. {parsed_inputs['action']} "
            + "is not a valid action in {VALID_ACTIONS.keys()}"
        )

    if not os.path.exists(parsed_inputs["settings_file"]):
        actions_toolkit.set_failed(
            f"Error while loading RepoManager Config. {parsed_inputs['settings_file']} does not exist"
        )

    scope = parsed_inputs.get("scope")
    target = parsed_inputs["target"]

    # Resolve 'self' for repo scope
    if target == "self":
        if scope not in (None, "repo"):
            actions_toolkit.set_failed(f"Error: target='self' is only valid for scope='repo', got scope='{scope}'")
        target = os.environ.get("GITHUB_REPOSITORY", None)
        if target is None:
            actions_toolkit.set_failed(
                "Error getting inputs. target is 'self' and GITHUB_REPOSITORY env var is not set."
            )
        parsed_inputs["target"] = target
        parsed_inputs["scope"] = "repo"
        scope = "repo"
    elif scope is None:
        if "/" in target:
            scope = "repo"
        else:
            actions_toolkit.set_failed(
                f"Error: target='{target}' has no '/' — please set 'scope' explicitly to 'org' or 'enterprise'."
            )
        parsed_inputs["scope"] = scope

    if scope == "repo" and "/" not in target:
        actions_toolkit.set_failed(f"Error: scope='repo' requires target in 'owner/repo' format, got '{target}'.")

    parsed_inputs["workspace_path"] = os.environ.get("RUNNER_WORKSPACE", None)
    if parsed_inputs["workspace_path"] is None:
        actions_toolkit.set_failed(
            "Error getting inputs. RUNNER_WORKSPACE env var is not set. Job likely not running on a GitHub agent."
        )

    if parsed_inputs["github_server_url"] is None:
        parsed_inputs["github_server_url"] = os.environ.get("GITHUB_SERVER_URL", None)
        if parsed_inputs["github_server_url"] is None:
            actions_toolkit.set_failed(
                "Error getting inputs. github_server_url is 'none' and "
                + "GITHUB_SERVER_URL env var is not set. Please set "
                + "INPUT_GITHUB_SERVER_URL or GITHUB_SERVER_URL in the env"
            )
    actions_toolkit.debug(f"github_server_url: {parsed_inputs['github_server_url']}")
    actions_toolkit.debug(f"github_workspace: {parsed_inputs['workspace_path']}")

    if scope == "repo":
        parsed_inputs["repo_object"] = get_repo()
    elif scope == "org":
        parsed_inputs["org_object"] = get_org_by_name(target)
    elif scope == "enterprise":
        # No first-class PyGitHub Enterprise object — store slug + requester
        parsed_inputs["enterprise_slug"] = target
        global client
        client = get_client() if "client" not in globals() else client
        parsed_inputs["enterprise_requester"] = client._Github__requester
    else:
        actions_toolkit.set_failed(f"Error: unknown scope '{scope}'. Must be 'repo', 'org', or 'enterprise'.")

    return parsed_inputs


def attr_to_kwarg(attr_name: str, obj: Any, kwargs: dict, transform_key: str = None):
    value = getattr(obj, attr_name, None)
    if value is not None:
        if transform_key is None:
            kwargs[attr_name] = value
        else:
            kwargs[transform_key] = value


# Allows use to extract a certain field on a list of objects into a list of strings etc.
def objary_to_list(attr_name: str, obj: Any):
    return list(map(getattr, obj, repeat(attr_name)))
