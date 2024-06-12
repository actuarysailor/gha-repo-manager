import sys
import json
import pandas as pd

from actions_toolkit import core as actions_toolkit
from actions_toolkit.file_command import issue_file_command

from pydantic import ValidationError

from yaml import YAMLError

from repo_manager.schemas import load_config
from repo_manager.utils import get_inputs
from repo_manager.gh.settings import check_repo_settings, update_settings
from repo_manager.gh.labels import check_repo_labels, update_labels
from repo_manager.gh.collaborators import check_collaborators, update_collaborators
from repo_manager.gh.branch_protections import check_repo_branch_protections, update_branch_protections
from repo_manager.gh.secrets import check_repo_secrets, update_secrets
from repo_manager.gh.variables import check_variables, update_variables
from repo_manager.gh.environments import check_repo_environments, update_environments
from repo_manager.gh.files import check_files, update_files


CATEGORIES_TO_TABULATE = ["settings", "collaborators", "branch_protections", "files"]

COLUMN_NAME_MAP = {
    "settings": {"key": "Setting", "value": None},
    "collaborators": {"key": "Collaborator Type", "value": "Collaborator"},
    "branch_protections": {"key": "Branch", "value": "Protection"},
    "files": {"key": "File", "value": "Differences"},
}


def __flatten_differences__(input_dict: dict, fieldNames: dict[str, str]) -> dict:
    fieldName = fieldNames["key"]
    valueName = fieldNames["value"]
    result = {fieldName: [], valueName: []}
    for k1, v1 in input_dict.items():
        result[fieldName].append(k1)
        for k2, v2 in v1.items():
            result[valueName].append(f"{k2} {v2}")

    return result


def __dict_to_columns__(input_dict: dict, fieldNames: dict[str, str]) -> dict:
    result = {}
    for key, value in input_dict.items():
        if fieldNames is None:
            fieldName = key
            valueName = None
        elif key.lower() in ["missing", "extra", "diff"]:
            fieldName = "Differences"
            if isinstance(value, list):
                valueName = fieldNames["key"]
            else:
                valueName = fieldNames["value"]
        elif key.lower() in ["users", "teams"]:
            fieldName = "Collaborator Type"
            valueName = fieldNames["value"]
        else:
            fieldName = fieldNames["key"]
            valueName = fieldNames["value"]
        if result.get(fieldName, None) is None:
            result[fieldName] = []
        if isinstance(value, str | int | bool):
            result[fieldName].append(value)
        elif isinstance(value, list):
            if valueName is None:
                result[fieldName].append(str(value))
            else:
                result[fieldName].extend([key] * len(value))
                result[valueName] = value
        elif isinstance(value, dict):
            if valueName == "Differences":
                subDict = __flatten_differences__(value, fieldNames)
            else:
                subDict = __dict_to_columns__(value, fieldNames if valueName is not None else None)
            if fieldName != valueName:
                result[fieldName].extend([key] * len(next(iter(subDict.values()))))
            for subKey, subValue in subDict.items():
                if result.get(subKey, None) is None:
                    result[subKey] = []
                result[subKey].extend(subValue)
        else:
            raise NotImplementedError(f"Unhandled case for {key} in {input_dict}")
    return result


def __tabularize_differences__(input_dict: dict, category: str) -> pd.DataFrame:
    fieldNames = COLUMN_NAME_MAP.get(category, None)
    flatDict = __dict_to_columns__(input_dict, fieldNames)
    return pd.DataFrame(flatDict)


def __markdown_summary__(diffs: dict[str, list[str] | dict[str, dict]], heading: str = "#") -> str:
    """Generate a markdown summary of the diffs"""
    summary = ""
    for category, items in diffs.items():
        summary += f"\n{heading} {category.capitalize()}\n"
        if category in CATEGORIES_TO_TABULATE:
            tbl = __tabularize_differences__(items, category)
            summary += pd.DataFrame(tbl).to_markdown()
        elif isinstance(items, list):
            summary += "\n".join([f"- {item}" for item in items])
        elif isinstance(items, dict):
            summary += __markdown_summary__(diffs[category], heading + "#")
        summary += "\n"
    return summary


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
    if inputs["action"] == "validate":
        actions_toolkit.set_output("result", f"Validated {inputs['settings_file']}")
        actions_toolkit.debug(json_diff := json.dumps({}))
        actions_toolkit.set_output("diff", json_diff)
        sys.exit(0)
    actions_toolkit.info(f"Config from {inputs['settings_file']} validated.")

    check_result = True
    diffs = {}
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
        check_files: ("files", config.files),
    }.items():
        check_name, to_check = to_check
        if to_check is not None:
            this_check, this_diffs = check(inputs["repo_object"], to_check)
            check_result &= this_check
            if this_diffs is not None:
                diffs[check_name] = this_diffs

    actions_toolkit.debug(json_diff := json.dumps(diffs))
    actions_toolkit.set_output("diff", json_diff)

    if inputs["action"] == "check":
        if not check_result:
            issue_file_command("STEP_SUMMARY", __markdown_summary__(diffs))
            if inputs["fail_on_diff"] == "true":
                actions_toolkit.set_output("result", "Check failed, diff detected")
                actions_toolkit.set_failed("Diff detected")
            else:
                actions_toolkit.warning("Diff detected")
        actions_toolkit.set_output("result", "Check passed")
        sys.exit(0)

    if inputs["action"] == "apply":
        errors = []
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
            update_files: ("files", config.files, diffs.get("files", None)),
        }.items():
            update_name, to_update, categorical_diffs = to_update
            if categorical_diffs is not None:
                try:
                    application_errors = update(inputs["repo_object"], to_update, categorical_diffs)
                    if len(application_errors) > 0:
                        errors.append(application_errors)
                    else:
                        actions_toolkit.info(f"Synced {update_name}")
                except Exception as exc:
                    errors.append({"type": f"{update_name}-update", "error": f"{exc}"})

        if len(errors) > 0:
            actions_toolkit.error(json.dumps(errors))
            actions_toolkit.set_failed("Errors during apply")
        actions_toolkit.set_output("result", "Apply successful")


if __name__ == "__main__":
    main()
