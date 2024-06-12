from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Repository import Repository

from repo_manager.schemas.label import Label


def check_repo_labels(
    repo: Repository, config_labels: list[Label]
) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Checks a repo's labels vs our expected settings

    Args:
        repo (Repository): [description]
        secrets (List[Secret]): [description]

    """
    repo_labels = {label.name: label for label in repo.get_labels()}
    config_label_dict = {label.name: label for label in config_labels}
    config_label_dict.update({label.expected_name: label for label in config_labels if label.expected_name != label.name})

    diffs = {}

    missing = list(
        {label.expected_name for label in filter(lambda label: label.exists and label.name not in repo_labels.keys() and label.expected_name not in repo_labels.keys(), config_labels)}
    )
    if len(missing) > 0:
        diffs["missing"] = missing

    extra = list(
        {label.expected_name for label in filter(lambda label: not label.exists and (label.name in repo_labels.keys() or label.expected_name in repo_labels.keys()), config_labels)}
    )
    if len(extra) > 0:
        diffs["extra"] = extra

    diff = {}
    labels_to_check = list(
        {label.name for label in filter(lambda label: label.exists and (label.name in repo_labels.keys()), config_labels)}.union(
        {label.expected_name for label in filter(lambda label: label.exists and (label.expected_name in repo_labels.keys() and label.name != label.expected_name), config_labels)})
    )
    for label_name in labels_to_check:
        if config_label_dict[label_name].expected_name != label_name:
            diff[label_name] = {"name": {
                "expected": config_label_dict[label_name].expected_name,
                "found":  label_name
                }
            }
        if config_label_dict[label_name].color is not None:
            if config_label_dict[label_name].color_no_hash.lower() != repo_labels[label_name].color.lower():
                diff[label_name] = {
                    "color": f"Expected {config_label_dict[label_name].color} found {repo_labels[label_name].color}"
                }
        if config_label_dict[label_name].description is not None:
            if config_label_dict[label_name].description != repo_labels[label_name].description:
                diff[label_name] = {
                    "description": f"Expected {config_label_dict[label_name].description} found {repo_labels[label_name].description}"
                }

    if len(diff) > 0:
        diffs["diff"] = diff

    if len(diffs) > 0:
        return False, diffs

    return True, None


def update_labels(
    repo: Repository, labels: list[Label], diffs: tuple[dict[str, list[str] | dict[str, Any]]]
) -> set[str]:
    """Updates a repo's labels to match the expected settings

    Args:
        repo (Repository): [description]
        labels (List[Label]): [description]

    Returns:
        set[str]: [description]
    """
    errors = []
    label_dict = {label.name: label for label in labels}
    for issue_type in diffs.keys():
        label_names = diffs[issue_type] if issue_type != "diff" else diffs[issue_type].keys()
        for label_name in label_names:
            if issue_type == "extra":
                try:
                    this_label = repo.get_label(label_name)
                    this_label.delete()
                    actions_toolkit.info(f"Deleted {label_name}")
                except Exception as exc:  # this should be tighter
                    errors.append({"type": "label-delete", "name": label_name, "error": f"{exc}"})
            elif issue_type == "missing":
                try:
                    repo.create_label(
                        label_dict[label_name].expected_name,
                        "ffffff" if label_dict[label_name].color_no_hash is None
                        else label_dict[label_name].color_no_hash,
                        label_dict[label_name].expected_name if label_dict[label_name].expected_name is not None
                        else "",
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
                    this_label = repo.get_label(label_name)
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
    return errors
