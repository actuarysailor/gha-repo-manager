import os

from repo_manager.main import main


os.environ["INPUT_GITHUB_SERVER_URL"] = os.environ["GITHUB_SERVER_URL"]
os.environ["INPUT_REPO"] = "self"
os.environ["INPUT_ACTION"] = "check"
os.environ["INPUT_SETTINGS_FILE"] = ".github/settings.yml"

# main() # not sure why this is failing...
