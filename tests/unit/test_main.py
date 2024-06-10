import os

from repo_manager.main import main


os.environ["GITHUB_SERVER_URL"] = "https://github.com"
os.environ["INPUT_REPO"] = "self"
os.environ["INPUT_ACTION"] = "check"
os.environ["INPUT_SETTINGS_FILE"] = ".github/settings.yml"

main()