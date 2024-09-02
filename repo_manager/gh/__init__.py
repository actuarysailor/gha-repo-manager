from functools import lru_cache

from github import Github, GithubIntegration, Auth
from github.GithubException import GithubException, UnknownObjectException


# https://github.com/PyGithub/PyGithub/blob/main/doc/examples/Authentication.rst
# https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/about-authentication-with-a-github-app
def __get_app_auth__(api_url: str, app_id: int, private_key: str) -> GithubIntegration:
    """Authenticate with GitHub as an app"""
    if not isinstance(app_id, str) or not isinstance(private_key, str):
        raise TypeError("app_id and private_key must be provided when attempting to authenticate as an installed app")
    auth = Auth.AppAuth(app_id=app_id, private_key=private_key)
    return GithubIntegration(auth=auth, base_url=api_url)


def __run_as_installed_app__(
    api_url: str, app_id: int, private_key: str, owner: str
) -> tuple[Github, dict]:
    """Uses the repo or owner to authenticate as an installed app"""
    ga = __get_app_auth__(api_url, app_id, private_key)
    for gi in ga.get_installations():
        if gi.raw_data["account"]["login"] == owner:
            break
    if gi.raw_data["account"]["login"] != owner:
        gi = None
    if gi is None:
        raise ValueError("Either owner or repo must be provided")
    perms = gi.raw_data["permissions"]
    return gi.get_github_for_installation(), perms


@lru_cache
def get_github_client(
    api_url: str,
    owner: str,
    token: str | None,
    app_id: int | None,
    private_key: str | None,
    **kwargs,
) -> tuple[Github, dict]:
    """Returns an instantiated interface with the GitHub API"""
    if token is None:
        return __run_as_installed_app__(api_url, app_id, private_key, owner)
    else:
        auth = Auth.Token(token)
        return Github(auth=auth, base_url=api_url), {}


__all__ = ["get_github_client", "GithubException", "UnknownObjectException"]
