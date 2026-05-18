from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Organization import Organization

from repo_manager.schemas.team import Team, TeamMember, TeamRepository


def _name_to_slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def _resolve_repo_full_name(org_login: str, repo_name: str) -> str:
    return repo_name if "/" in repo_name else f"{org_login}/{repo_name}"


def _get_team_repo_permission(repo) -> str:
    perms = repo.permissions
    if perms is None:
        return "pull"
    for level in ("admin", "maintain", "push", "triage"):
        if getattr(perms, level, False):
            return level
    return "pull"


def _diff_members(github_team, config_members: list[TeamMember]) -> dict[str, Any]:
    try:
        all_members = {m.login for m in github_team.get_members()}
        maintainers = {m.login for m in github_team.get_members(role="maintainer")}
    except Exception:
        return {}

    missing, extra, wrong_role = [], [], {}
    for m in config_members:
        if m.exists is False:
            if m.username in all_members:
                extra.append(m.username)
            continue
        if m.username not in all_members:
            missing.append(m.username)
        else:
            is_maintainer = m.username in maintainers
            if is_maintainer != (m.role.value == "maintainer"):
                wrong_role[m.username] = {
                    "expected": m.role.value,
                    "found": "maintainer" if is_maintainer else "member",
                }

    diffs: dict[str, Any] = {}
    if missing:
        diffs["missing"] = missing
    if extra:
        diffs["extra"] = extra
    if wrong_role:
        diffs["wrong_role"] = wrong_role
    return diffs


def _diff_repos(org: Organization, github_team, config_repos: list[TeamRepository]) -> dict[str, Any]:
    try:
        actual_repos = {repo.full_name: repo for repo in github_team.get_repos()}
    except Exception:
        return {}

    missing, extra, wrong_perm = [], [], {}
    for r in config_repos:
        full_name = _resolve_repo_full_name(org.login, r.name)
        if r.exists is False:
            if full_name in actual_repos:
                extra.append(full_name)
            continue
        if full_name not in actual_repos:
            missing.append(full_name)
        else:
            actual_perm = _get_team_repo_permission(actual_repos[full_name])
            if actual_perm != r.permission:
                wrong_perm[full_name] = {"expected": r.permission, "found": actual_perm}

    diffs: dict[str, Any] = {}
    if missing:
        diffs["missing"] = missing
    if extra:
        diffs["extra"] = extra
    if wrong_perm:
        diffs["wrong_permission"] = wrong_perm
    return diffs


def check_teams(org: Organization, config_teams: list[Team]) -> tuple[bool, dict[str, Any] | None]:
    """Check org teams against expected configuration."""
    existing = {t.slug: t for t in org.get_teams()}

    missing, extra, diff_map = [], [], {}

    for cfg in config_teams:
        slug = cfg.slug or _name_to_slug(cfg.name)
        match = existing.get(slug)

        if cfg.exists is False:
            if match is not None:
                extra.append(cfg.name)
            continue

        if match is None:
            missing.append(cfg.name)
            continue

        diffs: dict[str, Any] = {}
        if cfg.description is not None and cfg.description != match.description:
            diffs["description"] = {"expected": cfg.description, "found": match.description}
        if match.privacy != cfg.privacy.value:
            diffs["privacy"] = {"expected": cfg.privacy.value, "found": match.privacy}
        if cfg.parent_team_slug is not None:
            actual_parent = match.parent.slug if match.parent else None
            if actual_parent != cfg.parent_team_slug:
                diffs["parent_team_slug"] = {"expected": cfg.parent_team_slug, "found": actual_parent}
        if cfg.members is not None:
            member_diffs = _diff_members(match, cfg.members)
            if member_diffs:
                diffs["members"] = member_diffs
        if cfg.repositories is not None:
            repo_diffs = _diff_repos(org, match, cfg.repositories)
            if repo_diffs:
                diffs["repositories"] = repo_diffs

        if diffs:
            diff_map[cfg.name] = {**diffs, "_slug": slug}

    result: dict[str, Any] = {}
    if missing:
        result["missing"] = missing
    if extra:
        result["extra"] = extra
    if diff_map:
        result["diff"] = diff_map

    return (False, result) if result else (True, None)


def _sync_members(org: Organization, github_team, members: list[TeamMember], errors: list) -> None:
    from repo_manager.utils import get_client

    gh_client = get_client()
    for m in members:
        try:
            user = gh_client.get_user(m.username)
            if m.exists is False:
                github_team.remove_membership(user)
                actions_toolkit.info(f"Removed '{m.username}' from team '{github_team.name}'")
            else:
                github_team.add_membership(user, role=m.role.value)
                actions_toolkit.info(f"Synced '{m.username}' in '{github_team.name}' as {m.role.value}")
        except Exception as exc:
            errors.append(
                {"type": "team-member-sync", "team": github_team.name, "member": m.username, "error": str(exc)}
            )


def _sync_repos(org: Organization, github_team, repos: list[TeamRepository], errors: list) -> None:
    for r in repos:
        full_name = _resolve_repo_full_name(org.login, r.name)
        endpoint = f"{org.url}/teams/{github_team.slug}/repos/{full_name}"
        try:
            if r.exists is False:
                org._requester.requestJsonAndCheck("DELETE", endpoint)
                actions_toolkit.info(f"Removed '{full_name}' from team '{github_team.name}'")
            else:
                org._requester.requestJsonAndCheck("PUT", endpoint, input={"permission": r.permission})
                actions_toolkit.info(f"Set '{github_team.name}' -> '{full_name}': {r.permission}")
        except Exception as exc:
            errors.append({"type": "team-repo-sync", "team": github_team.name, "repo": full_name, "error": str(exc)})


def update_teams(
    org: Organization,
    config_teams: list[Team],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create, update, or delete teams to reconcile org state with config."""
    errors: list[dict] = []
    messages: list[str] = []
    config_by_name = {t.name: t for t in config_teams}

    for name in diffs.get("missing", []):
        cfg = config_by_name[name]
        try:
            create_kwargs: dict[str, Any] = {"name": cfg.name, "privacy": cfg.privacy.value}
            if cfg.description:
                create_kwargs["description"] = cfg.description
            if cfg.parent_team_slug:
                parent = org.get_team_by_slug(cfg.parent_team_slug)
                create_kwargs["parent_team_id"] = parent.id
            new_team = org.create_team(**create_kwargs)
            actions_toolkit.info(f"Created team '{name}'")
            messages.append(f"Created team '{name}'")
            if cfg.members:
                _sync_members(org, new_team, cfg.members, errors)
            if cfg.repositories:
                _sync_repos(org, new_team, cfg.repositories, errors)
        except Exception as exc:
            errors.append({"type": "team-create", "name": name, "error": str(exc)})

    for name in diffs.get("extra", []):
        cfg = config_by_name[name]
        slug = cfg.slug or _name_to_slug(name)
        try:
            team = org.get_team_by_slug(slug)
            team.delete()
            actions_toolkit.info(f"Deleted team '{name}'")
            messages.append(f"Deleted team '{name}'")
        except Exception as exc:
            errors.append({"type": "team-delete", "name": name, "error": str(exc)})

    for name, team_diff in diffs.get("diff", {}).items():
        cfg = config_by_name[name]
        slug = team_diff["_slug"]
        try:
            github_team = org.get_team_by_slug(slug)
        except Exception as exc:
            errors.append({"type": "team-fetch", "name": name, "error": str(exc)})
            continue

        update_kwargs: dict[str, Any] = {}
        if "description" in team_diff:
            update_kwargs["description"] = cfg.description or ""
        if "privacy" in team_diff:
            update_kwargs["privacy"] = cfg.privacy.value
        if "parent_team_slug" in team_diff:
            if cfg.parent_team_slug:
                try:
                    parent = org.get_team_by_slug(cfg.parent_team_slug)
                    update_kwargs["parent_team_id"] = parent.id
                except Exception as exc:
                    errors.append({"type": "team-parent-fetch", "name": name, "error": str(exc)})
            else:
                update_kwargs["parent_team_id"] = None

        if update_kwargs:
            try:
                github_team.edit(name=cfg.name, **update_kwargs)
                messages.append(f"Updated team metadata for '{name}'")
            except Exception as exc:
                errors.append({"type": "team-update", "name": name, "error": str(exc)})

        if "members" in team_diff and cfg.members:
            _sync_members(org, github_team, cfg.members, errors)
        if "repositories" in team_diff and cfg.repositories:
            _sync_repos(org, github_team, cfg.repositories, errors)

    return errors, messages
