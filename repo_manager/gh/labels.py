from typing import Any, Union

from actions_toolkit import core as actions_toolkit
from github.Organization import Organization
from github.Repository import Repository

from repo_manager.schemas.label import Label

Labelable = Union[Repository, Organization]


def _resolve_target(target: Labelable) -> Repository:
    """Resolve an Organization to its .github repo, since GitHub has no org-level labels API.
    Creates the .github repo if it does not exist."""
    if isinstance(target, Organization):
        try:
            return target.get_repo(".github")
        except Exception:
            actions_toolkit.info(f"Creating .github repository for org '{target.login}'")
            return target.create_repo(
                ".github",
                description="Organization-wide default community health files and settings",
                private=True,
                auto_init=True,
            )
    return target


def _get_all_labels(target: Labelable) -> dict[str, Any]:
    """Fetch all labels from a repo (or org's .github repo), returning a name→label dict."""
    repo = _resolve_target(target)
    return {label.name: label for label in repo.get_labels()}


def _get_label(target: Labelable, name: str):
    """Get a single label by name."""
    repo = _resolve_target(target)
    return repo.get_label(name)


def _create_label(target: Labelable, name: str, color: str, description: str = "") -> None:
    """Create a label on a repo or org's .github repo."""
    repo = _resolve_target(target)
    repo.create_label(name, color, description)



def check_repo_labels(
    repo: Labelable, config_labels: list[Label]
) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Checks a repo's labels vs our expected settings

    Args:
        repo (Repository): [description]
        secrets (List[Secret]): [description]

    """
    repo_labels = _get_all_labels(repo)
    config_label_dict = {label.name: label for label in config_labels}
    config_label_dict.update(
        {label.expected_name: label for label in config_labels if label.expected_name != label.name}
    )

    diffs = {}

    missing = list(
        {
            label.expected_name
            for label in filter(
                lambda label: label.exists
                and label.name not in repo_labels.keys()
                and label.expected_name not in repo_labels.keys(),
                config_labels,
            )
        }
    )
    if len(missing) > 0:
        diffs["missing"] = missing

    extra = list(
        {
            label.expected_name
            for label in filter(
                lambda label: not label.exists
                and (label.name in repo_labels.keys() or label.expected_name in repo_labels.keys()),
                config_labels,
            )
        }
    )
    if len(extra) > 0:
        diffs["extra"] = extra

    diff = {}
    labels_to_check = list(
        {
            label.name
            for label in filter(lambda label: label.exists and (label.name in repo_labels.keys()), config_labels)
        }.union(
            {
                label.expected_name
                for label in filter(
                    lambda label: label.exists
                    and (label.expected_name in repo_labels.keys() and label.name != label.expected_name),
                    config_labels,
                )
            }
        )
    )
    for label_name in labels_to_check:
        if config_label_dict[label_name].expected_name != label_name:
            diff[label_name] = {"name": {"expected": config_label_dict[label_name].expected_name, "found": label_name}}
        if config_label_dict[label_name].color is not None:
            if config_label_dict[label_name].color_no_hash.lower() != repo_labels[label_name].color.lower():
                diff[label_name] = {
                    "color": {
                        "expected": config_label_dict[label_name].color_no_hash.lower(),
                        "found": None if (repo_labels[label_name].color is None) else repo_labels[label_name].color,
                    }
                }
        if config_label_dict[label_name].description is not None:
            if config_label_dict[label_name].description != repo_labels[label_name].description:
                diff[label_name] = {
                    "description": {
                        "expected": config_label_dict[label_name].description,
                        "found": None
                        if (repo_labels[label_name].description is None)
                        else repo_labels[label_name].description,
                    }
                }

    if len(diff) > 0:
        diffs["diff"] = diff

    if len(diffs) > 0:
        return False, diffs

    return True, None


def update_labels(
    repo: Labelable, labels: list[Label], diffs: tuple[dict[str, list[str] | dict[str, Any]]]
) -> tuple[set[str], set[str]]:
    """Updates a repo's labels to match the expected settings

    Args:
        repo (Repository): [description]
        labels (List[Label]): [description]

    Returns:
        set[str]: [description]
    """
    errors = []
    label_dict = {label.name: label for label in labels}
    label_dict.update({label.expected_name: label for label in labels})
    for issue_type in diffs.keys():
        label_names = diffs[issue_type] if issue_type != "diff" else diffs[issue_type].keys()
        for label_name in label_names:
            if issue_type == "extra":
                try:
                    this_label = _get_label(repo, label_name)
                    this_label.delete()
                    actions_toolkit.info(f"Deleted {label_name}")
                except Exception as exc:  # this should be tighter
                    errors.append({"type": "label-delete", "name": label_name, "error": f"{exc}"})
            elif issue_type == "missing":
                try:
                    _create_label(
                        repo,
                        label_dict[label_name].expected_name,
                        "ffffff"
                        if label_dict[label_name].color_no_hash is None
                        else label_dict[label_name].color_no_hash,
                        label_dict[label_name].description
                        if label_dict[label_name].description is not None
                        else label_dict[label_name].expected_name,
                    )
                    actions_toolkit.info(f"Created label {label_name}")
                except Exception as exc:  # this should be tighter
                    errors.append(
                        {
                            "type": "label-create",
                            "name": label_name,
                            "error": f"{exc}",
                        }
                    )
            elif issue_type == "diff":
                try:
                    this_label = _get_label(repo, label_name)
                    this_label.edit(
                        label_dict[label_name].expected_name,
                        this_label.color
                        if label_dict[label_name].color_no_hash is None
                        else label_dict[label_name].color_no_hash,
                        this_label.description
                        if label_dict[label_name].description is None
                        else label_dict[label_name].description,
                    )
                    actions_toolkit.info(f"Updated label {label_name}")
                except Exception as exc:  # this should be tighter
                    errors.append(
                        {
                            "type": "label-update",
                            "name": label_name,
                            "error": f"{exc}",
                        }
                    )
    return errors, []
