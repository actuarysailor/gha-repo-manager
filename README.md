# Manage Administrative Repository Settings from Pull-Requests
<!-- ALL-CONTRIBUTORS-BADGE:START - Do not remove or modify this section -->
[![All Contributors](https://img.shields.io/badge/all_contributors-2-orange.svg?style=flat-square)](#contributors-)
<!-- ALL-CONTRIBUTORS-BADGE:END -->

<!-- action-docs-description source="action.yml" -->
### Description

Manage all Github repo settings from a YAML file, enabling greater change control, transparency, and auditability.
<!-- action-docs-description source="action.yml" -->

## Authentication

This action supports two authentication methods. Choose the one that best fits your use case.

### GitHub App (recommended for automated / scheduled workflows)

When this action runs on a schedule or is triggered by repository events (e.g., merges to `main`), commits, pull-requests, and API calls are attributed to **the actor that triggered the workflow** — usually a human user. Using a GitHub App instead means all activity is attributed to the **bot/app identity**, which provides a cleaner audit trail and avoids consuming a person's rate-limit quota.

**Setup steps:**

1. [Create a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) in your organization with the permissions listed in the table below.
2. Install the app on the organizations and/or repositories you want it to manage.
3. Store the **App ID** as an organization variable (e.g. `REPO_MANAGER_APP_ID`) — it is not a secret.
4. Store the **Private Key** as an organization secret (e.g. `REPO_MANAGER_PRIVATE_KEY`) — treat it like a password.

```yaml
- name: Run RepoManager (GitHub App)
  uses: actuarysailor/gha-repo-manager@v2.0.0
  with:
    action: apply
    settings_file: .github/settings.yml
    app_id: ${{ vars.REPO_MANAGER_APP_ID }}
    private_key: ${{ secrets.REPO_MANAGER_PRIVATE_KEY }}
```

### Personal Access Token (PAT) (recommended for ad-hoc / manual runs)

If you are manually triggering this action to make bulk changes across multiple repositories — effectively performing actions *on your own behalf* — a PAT is a simpler choice. All activity will be attributed to your user account, which is fine when you intentionally want your identity visible in the audit log.

```yaml
- name: Run RepoManager (PAT)
  uses: actuarysailor/gha-repo-manager@v2.0.0
  with:
    action: apply
    settings_file: .github/settings.yml
    token: ${{ secrets.GITHUB_PAT }}
```

> **Tip:** Prefer a [fine-grained PAT](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token#creating-a-fine-grained-personal-access-token) scoped to only the repositories and permissions you actually need.

### Required Permissions

The action will **not fail** if the token or app lacks permission for a particular settings category. It will emit a warning in the run log and step summary, clearly listing the missing permissions, and then continue processing the remaining categories.

Grant only the permissions you need for the features you use:

| `settings.yml` section | GitHub App permission | PAT scope | Notes |
|---|---|---|---|
| `settings` | `administration: write` | `repo` | Repository-level settings, merge strategies, default branch |
| `collaborators` | `members: write` (org repos)<br>`administration: write` (user repos) | `repo` | User and team access control |
| `labels` | `issues: write` | `repo` | Issue and pull-request labels |
| `branch_protections` | `administration: write` | `repo` | Branch protection rules |
| `secrets` (actions) | `secrets: write` | `repo` | Actions secrets |
| `secrets` (dependabot) | `dependabot_secrets: write` | `repo`, `admin:org` | Dependabot secrets |
| `variables` | `variables: write` | `repo` | Actions variables |
| `environments` | `environments: write` | `repo` | Deployment environments, environment secrets & variables |
| `batch_file_operations` | `contents: write`<br>`pull_requests: write` | `repo` | File copy/move/delete; creates PRs for file changes |

#### Minimum permissions for common use cases

| Use case | GitHub App permissions | PAT scopes |
|---|---|---|
| Read-only drift check (`action: check`) | `administration: read`, `contents: read`, `issues: read`, `secrets: read` | `repo` (read-only fine-grained PAT) |
| Manage labels only | `issues: write` | `repo` |
| Full management | All permissions in the table above | `repo`, `admin:org` (for Dependabot secrets) |



**Why would you want to do this?**
* Adhere to principal of least-privilegas for developers and other contributors.
  * *Allows contributors without repo admin privileges to propose admin changes for review by repo owners and maintainers*
* Enables contributors without admin rights ability to maintain variables, secrets, deployment environments, etc.
  * *GitHub restricts many of these items to the repo admin role, but granting this role to many people runs in direct conflict to requirements by audit teams, generally accepted best practices for governance, or corporate standards and requirements*
* Ability to centralize maintenance of repo configurations and permission standards
  * *Use of [.github repo](https://www.freecodecamp.org/news/how-to-use-the-dot-github-repository/) or some other centralized repo*
    * Make directories containing standardized example workflows and use the file-copy to maintain all CI/CD workflows matching a given regex pattern for repo names
    * Similary, add a settings.yml file to that directory to standardize variables, secrets, access control lists, etc.

**What Items You May Manage:**

* repos *configure external repos*
* repo settings
* branch protection(s)
* labels
* secrets
* variables
* deployment environments
* contributors *e.g. access control lists or ACL management*
* files *such as CI/CD, codeowners, issue and pull-request templates, etc.*

See [examples/settings.yml](./examples/settings.yml) for an example config file. The schemas for this file are in [repo_manager.schemas](./repo_magager/schemas).

### File Management -- Experimental

File management can copy files from your local environment to a target repo, copy files from one location to another in the target repo, move files in the target repo, and delete files in the target repo.

File operations are performed using the Github BLOB API and your PAT. Each file operation is a separate commit.

This feature is helpful to keep workflows or settings file in sync from a central repo to many repos.

### Example workflow

```yaml
name: Run Repo Manager
on: [workflow_dispatch]
jobs:
  repo-manager:
    runs-on: ubuntu-latest
    steps:
    - name: Checkout
      uses: actions/checkout@v4.1.6

    - name: Run RepoManager
      # you should always reference a version tag to ensure that your use of an action never changes until you update it
      uses: actuarysailor/gha-repo-manager@v2.0.0
      with:
        # Apply your settings to the repo, can also be check to just check repo settings vs your file or validate, to validate your
        # file is valid
        action: apply
        settings_file: .github/settings.yml
        # See the Authentication section above for when to use a PAT vs a GitHub App.
        # See the Required Permissions table for the exact scopes/permissions needed.
        token: ${{ secrets.GITHUB_PAT }}

```

<!-- action-docs-inputs source="action.yml" -->
### Inputs

| name | description | required | default |
| --- | --- | --- | --- |
| `action` | <p>What action to take with this action. One of validate, check, or apply. Validate will validate your settings file, but not touch your repo. Check will check your repo with your settings file and output a report of any drift. Apply will apply the settings in your settings file to your repo</p> | `false` | `check` |
| `settings_file` | <p>What yaml file to use as your settings. This is local to runner running this action.</p> | `false` | `.github/settings.yml` |
| `repo` | <p>What repo to perform this action on. Default is self, as in the repo this action is running in</p> | `false` | `self` |
| `github_server_url` | <p>Set a custom github server url for github api operations. Useful if you're running on GHE. Will try to autodiscover from env.GITHUB<em>SERVER</em>URL if left at default</p> | `false` | `""` |
| `token` | <p>What github token to use with this action (one of token or app_id is required).</p> | `false` | `""` |
| `app_id` | <p>What github app id to use with this action (one of token or app_id is required).</p> | `false` | `""` |
| `private_key` | <p>What github app private key to use with this action (required if using an app_id to authenticate).</p> | `false` | `""` |
| `fail_on_diff` | <p>Fail the action if the repo settings differ from the settings file. Default is false. Note, this only applies if the action is set to 'check'</p> | `false` | `false` |
<!-- action-docs-inputs source="action.yml" -->

<!-- action-docs-outputs source="action.yml" -->
### Outputs

| name | description |
| --- | --- |
| `result` | <p>Result of the action</p> |
| `diff` | <p>Diff of this action, dumped to a json string</p> |
<!-- action-docs-outputs source="action.yml" -->

<!-- action-docs-runs source="action.yml" -->
### Runs

This action is a `docker` action.
<!-- action-docs-runs source="action.yml" -->

## Contributors

Please see our [Contribution Guide](./CONTRIBUTING.md) for more info on how you can contribute. All contributors and participants in this repo must follow our [Code of Conduct](./CODE_OF_CONDUCT.md).
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

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
