# Manage Administrative Repository Settings from Pull Requests

<!-- ALL-CONTRIBUTORS-BADGE:START - Do not remove or modify this section -->
[![All Contributors](https://img.shields.io/badge/all_contributors-2-orange.svg?style=flat-square)](#contributors-)
<!-- ALL-CONTRIBUTORS-BADGE:END -->

<!-- action-docs-description source="action.yml" -->
### Description

Manage all GitHub repo settings from a YAML file, enabling greater change control, transparency, and auditability.
<!-- action-docs-description source="action.yml" -->

---

## Table of Contents

- [Why Use This?](#why-use-this)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
  - [GitHub App (recommended)](#github-app-recommended)
  - [Personal Access Token (PAT)](#personal-access-token-pat)
  - [Required Permissions](#required-permissions)
- [Action Inputs & Outputs](#action-inputs--outputs)
- [The `settings.yml` Schema](#the-settingsyml-schema)
  - [Repository Settings](#repository-settings)
  - [Collaborators](#collaborators)
  - [Labels](#labels)
  - [Branch Protections](#branch-protections)
  - [Secrets](#secrets)
  - [Variables](#variables)
  - [Environments](#environments)
  - [File Sync (`batch_file_operations`)](#file-sync-batch_file_operations)
- [Usage Patterns](#usage-patterns)
  - [Self-managed (single repo)](#self-managed-single-repo)
  - [Centralized governance (many repos)](#centralized-governance-many-repos)
  - [Drift detection on pull requests](#drift-detection-on-pull-requests)
- [Debugging](#debugging)
- [Contributing](#contributing)

---

## Why Use This?

- **Principle of least privilege for contributors** — contributors without repo admin rights can propose admin-level changes (branch protections, secrets, environments, etc.) via a pull request, subject to review by owners and maintainers.
- **Audit trail** — every change is a git commit, reviewed in a PR, and attributed to a bot identity rather than a person's account (when using a GitHub App).
- **Centralized governance** — run from a `.github` org repo or any central repo to enforce consistent settings, workflows, labels, and access control across many repos at once.
- **Drift detection** — run in `check` mode on a schedule or on PR to surface configuration drift before it becomes a problem.

---

## Quick Start

1. Create a `.github/settings.yml` in your repo (see [The `settings.yml` Schema](#the-settingsyml-schema)).
2. Add this workflow:

```yaml
name: Repo Manager
on:
  push:
    branches: [main]
    paths: ['.github/settings.yml']

jobs:
  apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actuarysailor/gha-repo-manager@v2.2.3
        with:
          action: apply
          settings_file: .github/settings.yml
          token: ${{ secrets.GITHUB_PAT }}
```

3. Push a change to `.github/settings.yml` — the action will apply it automatically.

> For production use, prefer a **GitHub App** over a PAT. See [Authentication](#authentication).

---

## Authentication

### GitHub App (recommended)

Using a GitHub App means all activity is attributed to a **bot identity**, not a person's account. This provides a cleaner audit trail, avoids consuming user rate-limit quota, and is the best choice for scheduled or cross-repo workflows.

**Setup:**

1. [Create a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) with the permissions from the table below.
2. Install the app on the organizations and/or repos you want it to manage.
3. Store the **App ID** as a variable (e.g. `REPO_MANAGER_APP_ID`) — it is not a secret.
4. Store the **Private Key** as a secret (e.g. `REPO_MANAGER_PRIVATE_KEY`).

```yaml
- uses: actuarysailor/gha-repo-manager@v2.2.3
  with:
    action: apply
    settings_file: .github/settings.yml
    app_id: ${{ vars.REPO_MANAGER_APP_ID }}
    private_key: ${{ secrets.REPO_MANAGER_PRIVATE_KEY }}
```

### Personal Access Token (PAT)

A PAT is simpler for ad-hoc or manual runs where you want activity attributed to your own account.

```yaml
- uses: actuarysailor/gha-repo-manager@v2.2.3
  with:
    action: apply
    settings_file: .github/settings.yml
    token: ${{ secrets.GITHUB_PAT }}
```

> **Tip:** Use a [fine-grained PAT](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token) scoped to only the repos and permissions you need.

### Required Permissions

The action will **not fail** when the token or app lacks permission for a category — it emits a warning in the run log and step summary listing the missing permission, then continues with the remaining categories.

Grant only the permissions you need for the features you use:

| `settings.yml` section | GitHub App permission | PAT scope | Notes |
|---|---|---|---|
| `settings` | `administration: write` | `repo` | Repo settings, merge strategies, default branch |
| `collaborators` | `members: write` (org repos)<br>`administration: write` (user repos) | `repo` | User and team access |
| `labels` | `issues: write` | `repo` | Issue and PR labels |
| `branch_protections` | `administration: write` | `repo` | Branch protection rules |
| `secrets` (Actions) | `secrets: write` | `repo` | Actions secrets |
| `secrets` (Dependabot) | `dependabot_secrets: write` | `repo`, `admin:org` | Dependabot secrets |
| `variables` | `variables: write` | `repo` | Actions variables |
| `environments` | `environments: write`, `actions: read` | `repo` | Deployment environments, env secrets & variables |
| `batch_file_operations` | `contents: write`, `pull_requests: write` | `repo` | File sync; creates/updates PRs |

> **Note on `environments`:** The GitHub API requires `actions: read` in addition to `environments: write` for the list-environments endpoint — grant both or the category will be skipped with a permission warning.

**Minimum permissions for common scenarios:**

| Scenario | GitHub App permissions | PAT scopes |
|---|---|---|
| Read-only drift check (`action: check`) | `administration: read`, `contents: read`, `issues: read`, `secrets: read` | `repo` (read-only fine-grained PAT) |
| Labels only | `issues: write` | `repo` |
| Full management | All permissions above | `repo`, `admin:org` |

---

## Action Inputs & Outputs

<!-- action-docs-inputs source="action.yml" -->
### Inputs

| name | description | required | default |
| --- | --- | --- | --- |
| `action` | <p>What action to take. One of:<br>• `validate` — validate the settings file without touching the repo<br>• `check` — compare repo state against the settings file and report drift<br>• `apply` — apply the settings file to the repo</p> | `false` | `check` |
| `settings_file` | <p>Path to your settings YAML file, relative to the runner workspace.</p> | `false` | `.github/settings.yml` |
| `repo` | <p>The repo to act on. Use `owner/repo-name` for a different repo, or leave as `self` to act on the repo the workflow is running in.</p> | `false` | `self` |
| `github_server_url` | <p>Custom GitHub server URL for GitHub Enterprise Server (GHES). Auto-detected from `GITHUB_SERVER_URL` if not set.</p> | `false` | `""` |
| `token` | <p>GitHub PAT to authenticate with. One of `token` or `app_id` is required.</p> | `false` | `""` |
| `app_id` | <p>GitHub App ID to authenticate with. One of `token` or `app_id` is required.</p> | `false` | `""` |
| `private_key` | <p>GitHub App private key. Required when using `app_id`.</p> | `false` | `""` |
| `fail_on_diff` | <p>Exit with a non-zero code if drift is detected. Only applies when `action: check`.</p> | `false` | `false` |
<!-- action-docs-inputs source="action.yml" -->

<!-- action-docs-outputs source="action.yml" -->
### Outputs

| name | description |
| --- | --- |
| `result` | Human-readable result string (e.g. `Check passed`, `Applied successfully`). |
| `diff` | JSON string containing all detected differences between the settings file and the repo. |
<!-- action-docs-outputs source="action.yml" -->

<!-- action-docs-runs source="action.yml" -->
### Runs

This action is a `docker` action.
<!-- action-docs-runs source="action.yml" -->

---

## The `settings.yml` Schema

All sections are optional — omit any section to leave those settings untouched.

See [`examples/settings.yml`](./examples/settings.yml) for a fully annotated reference file, and [`examples/settings-clear.yml`](./examples/settings-clear.yml) for an example that resets/removes everything.

---

### Repository Settings

```yaml
settings:
  description: "A short description shown on GitHub."
  homepage: "https://example.com"        # Set to "" to clear
  topics:                                # Set to [] to clear; omit to leave unchanged
    - my-topic
  private: false
  has_issues: true
  has_projects: true
  has_wiki: true
  has_downloads: true
  default_branch: main
  allow_squash_merge: true
  allow_merge_commit: false
  allow_rebase_merge: false
  delete_branch_on_merge: true
  enable_automated_security_fixes: true
  enable_vulnerability_alerts: true
```

Any setting that is omitted leaves the repo's current value unchanged. If a setting is present in `settings.yml`, it will always be enforced.

---

### Collaborators

Controls user and team access. Setting `exists: false` removes a collaborator or team.

```yaml
collaborators:
  - name: some-user         # GitHub login
    type: user
    permission: push        # push | pull | triage | maintain | admin | <custom role>
    exists: true

  - name: my-org/my-team    # org/team-slug or just team-slug (resolved against repo owner org)
    type: team
    permission: maintain
    exists: true

  - name: old-user
    type: user
    permission: push
    exists: false           # Removes this collaborator
```

---

### Labels

Creates, renames, or deletes issue/PR labels. A rename or delete targeting a label that doesn't exist emits a warning but does not fail the run.

```yaml
labels:
  - name: help wanted
    new_name: first-timers-only   # Renames the label
    color: "0075ca"               # Hex color without #
    description: "Good for newcomers"

  - name: old-label
    exists: false                 # Deletes the label
```

---

### Branch Protections

```yaml
branch_protections:
  - name: main
    exists: true          # Set to false to remove branch protection
    protection:
      pr_options:
        required_approving_review_count: 1   # 1–6
        dismiss_stale_reviews: true
        require_code_owner_reviews: true
        # dismissal_restrictions:
        #   users: []
        #   teams: []
      # required_status_checks:
      #   strict: true
      #   checks:
      #     - lint
      #     - test
      # require_conversation_resolution: true
      enforce_admins: true
      require_linear_history: true
      allow_force_pushes: false
      allow_deletions: false
      block_creations: true
      restrictions:
        users: []
        teams: []
```

Branch protection can only be applied to branches that already exist in the repo.

---

### Secrets

Manages Actions and Dependabot secrets. Secrets are always written (the action cannot read back secret values to detect drift, so they are re-applied on every run).

```yaml
secrets:
  - key: MY_SECRET
    env: ENV_VAR_NAME       # Read the value from this env variable on the runner
    exists: true            # Set to false to delete the secret

  - key: ANOTHER_SECRET
    value: literal-value    # Embed the value directly — avoid for real secrets!

  - key: OPTIONAL_SECRET
    env: MAYBE_SET
    required: false         # If MAYBE_SET is not set in env, skip without error

  - key: DEPENDABOT_SECRET
    env: MY_VALUE
    type: dependabot        # Creates a Dependabot secret instead of an Actions secret
```

> **Tip:** Set environment variables on the workflow job from your repo's own secrets to sync secrets from one repo to another:
> ```yaml
> env:
>   MY_VALUE: ${{ secrets.MY_VALUE }}
> ```

---

### Variables

Same structure as secrets, but values are readable — the action can detect drift and skip updates when the value is already correct.

```yaml
variables:
  - key: MY_VARIABLE
    value: "some value"
    exists: true            # Set to false to delete the variable
```

---

### Environments

Manages deployment environments, including their secrets, variables, reviewers, wait timers, and deployment branch policies.

```yaml
environments:
  - name: production
    exists: true            # Set to false to delete the environment

    wait_timer: 30          # Minutes to delay deployment (0–43200)
    prevent_self_review: true

    reviewers:              # Up to 6 users or teams
      - name: my-org/my-team
        type: team
      - name: some-user
        type: user

    deployment_branch_policy:
      protected_branches: false     # Exactly one of these must be true
      custom_branch_policies: true

    branch_name_patterns:           # Required when custom_branch_policies: true
      - main
      - release/*

    secrets:
      - key: PROD_SECRET
        env: PROD_SECRET_VALUE
        type: environments/production
        exists: true

    variables:
      - key: PROD_VAR
        value: "prod-value"
        type: environments/production
        exists: true
```

> **Permission note:** `environments: write` alone is not sufficient. The GitHub API also requires `actions: read` for the list-environments endpoint. Grant both permissions or the `environments` category will be skipped with a warning. See [Required Permissions](#required-permissions).

---

### File Sync (`batch_file_operations`)

Copies, moves, renames, or deletes files in a target repo. Changes are committed to a `repomgr/updates-to-<target-branch>` branch and a pull request is opened (or updated if one already exists).

**Key rules:**
- `src_file` is always a path in the **local (runner) repo** unless prefixed with `remote://`, which means the file is in the **target repo**.
- `dest_file` is always a path in the **target repo**. Defaults to the same path as `src_file` if omitted.
- File operations within a batch are applied in order.
- **Idempotent** — if a source file's git commit SHA has already been synced into the destination branch's history (tracked via a `[synced-from-sha:<sha>]` marker in commit messages), that file is skipped automatically on re-run.
- If the sync branch already exists (e.g. a prior PR is still open), new commits are added on top and the PR description is updated — no duplicate PRs are created.

```yaml
batch_file_operations:
  - target_branch: main     # Branch in the target repo to open a PR against
    skip: false             # Set to true to skip this batch entirely
    commit_msg: "chore(sync): update shared workflows"

    files:
      # Copy a file from the local repo to the same path in the target repo
      - src_file: .github/workflows/ci.yml

      # Copy and rename
      - src_file: templates/issue-template.md
        dest_file: .github/ISSUE_TEMPLATE/bug-report.md

      # Move a file within the target repo (remote:// = file is already in target repo)
      - src_file: remote://OLD_PATH/file.txt
        dest_file: NEW_PATH/file.txt
        move: true

      # Delete a file from the target repo
      - src_file: remote://OLDDOC.md
        exists: false
```

---

## Usage Patterns

### Self-managed (single repo)

Apply settings to the repo the workflow runs in on every push to `main`:

```yaml
name: Apply Repo Settings
on:
  push:
    branches: [main]
    paths: ['.github/settings.yml']
  workflow_dispatch:

jobs:
  apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actuarysailor/gha-repo-manager@v2.2.3
        with:
          action: apply
          settings_file: .github/settings.yml
          app_id: ${{ vars.REPO_MANAGER_APP_ID }}
          private_key: ${{ secrets.REPO_MANAGER_PRIVATE_KEY }}
```

---

### Centralized governance (many repos)

Run from a central `.github` or governance repo to manage settings across many repos. Each repo gets its own settings file in the central repo:

```yaml
name: Enforce Repo Standards
on:
  push:
    branches: [main]
  schedule:
    - cron: '0 6 * * 1'   # Weekly drift check
  workflow_dispatch:

jobs:
  manage:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        repo: [my-org/repo-a, my-org/repo-b, my-org/repo-c]
    steps:
      - uses: actions/checkout@v4
      - uses: actuarysailor/gha-repo-manager@v2.2.3
        with:
          action: apply
          repo: ${{ matrix.repo }}
          settings_file: settings/${{ matrix.repo }}.yml
          app_id: ${{ vars.REPO_MANAGER_APP_ID }}
          private_key: ${{ secrets.REPO_MANAGER_PRIVATE_KEY }}
```

---

### Drift detection on pull requests

Check for configuration drift on every PR that touches `settings.yml`, without applying any changes:

```yaml
name: Check Repo Settings
on:
  pull_request:
    paths: ['.github/settings.yml']

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actuarysailor/gha-repo-manager@v2.2.3
        with:
          action: check
          fail_on_diff: true
          settings_file: .github/settings.yml
          app_id: ${{ vars.REPO_MANAGER_APP_ID }}
          private_key: ${{ secrets.REPO_MANAGER_PRIVATE_KEY }}
```

---

## Debugging

Enable [GitHub Actions debug logging](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/enabling-debug-logging) by setting the `ACTIONS_STEP_DEBUG` secret to `true` on your repo. This will output:

- The GitHub App installation permissions and repository selection at startup.
- A direct API probe against the failing endpoint whenever a `403` occurs, showing the exact permission required (`x-accepted-github-permissions` response header).
- Full input/output diffs for every settings category.

---

## Contributing

Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for how to contribute. All participants must follow the [Code of Conduct](./CODE_OF_CONDUCT.md).

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/actuarysailor"><img src="https://avatars.githubusercontent.com/u/1377314?v=4?s=100" width="100px;" alt="Andrew"/><br /><sub><b>Andrew</b></sub></a><br /><a href="#ideas-actuarysailor" title="Ideas, Planning, & Feedback">🤔</a> <a href="https://github.com/actuarysailor/gha-repo-manager/commits?author=actuarysailor" title="Tests">⚠️</a> <a href="https://github.com/actuarysailor/gha-repo-manager/commits?author=actuarysailor" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/actuarysailor"><img src="https://avatars.githubusercontent.com/u/24359398?v=4?s=100" width="100px;" alt="shiro"/><br /><sub><b>shiro</b></sub></a><br /><a href="https://github.com/actuarysailor/gha-repo-manager/issues?q=author%3Aactuarysailor" title="Bug reports">🐛</a> <a href="https://github.com/actuarysailor/gha-repo-manager/commits?author=actuarysailor" title="Code">💻</a></td>
    </tr>
  </tbody>
</table>
<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->
