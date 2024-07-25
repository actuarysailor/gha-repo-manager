# ruff: noqa: E501
# This code is automatically generated by actions.yml and make generate-inputs
###START_INPUT_AUTOMATION###
INPUTS = {
    "action": {
        "description": "What action to take with this action. One of validate, check, or apply. Validate will validate your settings file, but not touch your repo. Check will check your repo with your settings file and output a report of any drift. Apply will apply the settings in your settings file to your repo",
        "default": "check",
    },
    "settings_file": {
        "description": "What yaml file to use as your settings. This is local to runner running this action.",
        "default": ".github/settings.yml",
    },
    "repo": {
        "description": "What repo to perform this action on. Default is self, as in the repo this action is running in",
        "default": "self",
    },
    "github_server_url": {
        "description": "Set a custom github server url for github api operations. Useful if you're running on GHE. Will try to autodiscover from env.GITHUB_SERVER_URL if left at default"
    },
    "token": {
        "description": "What github token to use with this action (one of token or app_id is required).",
        "required": False,
    },
    "app_id": {
        "description": "What github app id to use with this action (one of token or app_id is required).",
        "required": False,
    },
    "private_key": {
        "description": "What github app private key to use with this action (required if using an app_id to authenticate).",
        "multiline": True,
        "required": False,
    },
    "fail_on_diff": {
        "description": "Fail the action if the repo settings differ from the settings file. Default is false. Note, this only applies if the action is set to 'check'",
        "default": False,
    },
}
###END_INPUT_AUTOMATION###
