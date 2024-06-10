import sys
import os
import json
import pandas as pd

from actions_toolkit import core as actions_toolkit

from pydantic import ValidationError

from yaml import YAMLError

from repo_manager.schemas import load_config
from repo_manager.utils import get_inputs
from repo_manager.gh.branch_protections import check_repo_branch_protections, update_branch_protections
from repo_manager.gh.files import check_files, update_files
from repo_manager.gh.labels import check_repo_labels, update_labels
from repo_manager.gh.secrets import check_repo_secrets, update_secrets
from repo_manager.gh.variables import check_variables, update_variables
from repo_manager.gh.collaborators import check_collaborators, update_collaborators
from repo_manager.gh.environments import check_repo_environments, update_environments
from repo_manager.gh.settings import check_repo_settings, update_settings


def __markdown_summary__(diffs: dict[str, list[str] | dict[str, str]], heading: str = "#") -> str:
    """Generate a markdown summary of the diffs"""
    summary = ""
    for category, items in diffs.items():
        summary += f"{heading} {category.capitalize()}\n"
        if isinstance(items, list):
            summary += "\n".join([f"- {item}" for item in items])
        elif isinstance(items, dict):
            for item, diff in items.items():
                if item in ("missing", "extra", "diff"):
                    summary += f"{heading}# {item.capitalize()}\n"
                    if item == "diff":
                        summary += pd.DataFrame(diff).to_markdown()
                    else:
                        summary += "\n".join([f"- {item}" for item in diff])
                else:
                    summary += __markdown_summary__(diff, heading + "#")
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
            os.system(f"echo '{__markdown_summary__(diffs)}' >> $GITHUB_STEP_SUMMARY")
            actions_toolkit.set_output("result", "Check failed, diff detected")
            actions_toolkit.set_failed("Diff detected")
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
