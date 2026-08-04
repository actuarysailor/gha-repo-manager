# Create virtual environment

- Follow [Visual Studio Code instructions to create a virtual environment](https://code.visualstudio.com/docs/python/environments#_creating-environments)
- Choose the `Venv` option
- Run the script below:

```
.venv\Scripts\activate
pip install Annotated
pip install pydantic
pip install pydantic_extra_types
pip install pygithub
pip install actions-toolkit
pip install pyyaml
```

# Spoof Environment Variables from GitHub Agent

Create a `.env` file in your root-directory of the repo (this repo)

```
RUNNER_WORKSPACE=C:\Temp
INPUT_GITHUB_SERVER_URL=none
INPUT_REPO=self
INPUT_TOKEN=********
INPUT_ACTION=check
INPUT_SETTINGS_FILE=./.github/settings.yml
```

# Unknown keys in `batch_file_operations` files now fail validation

`FileConfig` (each entry under a `files:` block) is declared with
`model_config = ConfigDict(extra="forbid")`. Any key that is not a recognised file
option raises a `ValidationError` instead of being silently ignored.

This was a deliberate change. Previously a typo such as:

```yaml
files:
  - src_file: templates/CLAUDE.md
    dest_file: CLAUDE.md
    overwite: false     # typo: 'overwite'
```

was accepted and dropped, so the entry quietly fell back to `overwrite: true` and
overwrote the destination — the exact outcome the option was added to prevent. A
silently-ignored safety flag is worse than no flag, so unknown keys are now errors.

If a settings file starts failing validation after upgrading, the error names the
offending key. Two things to check:

- Keys that belong on the **batch**, not the file. `commit_msg`, `target_branch`,
  and `skip` are `BranchFiles` options; on an individual file entry they never did
  anything. (The bundled `examples/settings.yml` had exactly this mistake.)
- Options that do not exist at all, such as `mode`.

Only `FileConfig` forbids extras. The other schemas still ignore unrecognised keys.

# Create a Python test file for debugging

Create a `test.py` file in your root-directory of the repo (this repo)

```
from repo_manager.main import main

main()
```
