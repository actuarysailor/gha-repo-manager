"""Tests for copy-once (``overwrite: false``) behaviour in file operations.

These exercise ``__check_files__`` against real on-disk git repositories, since the
skip decision is made from filesystem state and recorded in git history.
"""

from unittest.mock import MagicMock

import pytest
from git import Repo

from repo_manager.gh import files as files_module
from repo_manager.gh.files import _SYNC_SHA_MARKER, __check_files__, check_files, update_files
from repo_manager.schemas.file import BranchFiles, FileConfig


COMMIT_MSG = "ci(standards): Seed starter files"


def _init_repo(path, files=None):
    """Create a git repo at ``path`` with an initial commit, optionally seeded with files."""
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(path, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    # A repo needs at least one commit before HEAD diffs and active_branch work.
    (path / ".keep").write_text("")
    for name, content in (files or {}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    repo.git.add("-A")
    repo.index.commit("initial")
    return repo


@pytest.fixture(autouse=True)
def _reset_module_globals():
    """``__check_files__`` records its commits in module globals; isolate each test."""
    files_module.commitChanges = None
    files_module.commitCleanup = None
    yield
    files_module.commitChanges = None
    files_module.commitCleanup = None


@pytest.fixture
def source_dir(tmp_path, monkeypatch):
    """A plain (non-git) directory acting as the runner workspace."""
    src = tmp_path / "workspace"
    src.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(src))
    return src


# ---------------------------------------------------------------------------
# Log slug derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/org/repo.git", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("git@github.com:org/repo.git", "org/repo"),
        ("ssh://git@github.com/org/repo.git", "org/repo"),
        # __clone_repo__ embeds credentials in the remote URL; they must not survive.
        ("https://user:ghs_secrettoken@github.com/org/repo.git", "org/repo"),
    ],
)
def test_repo_slug_from_remote_url(tmp_path, url, expected):
    repo = _init_repo(tmp_path / "target")
    repo.create_remote("origin", url)
    slug = files_module.__repo_slug__(repo)
    assert slug == expected
    assert "ghs_secrettoken" not in slug


def test_repo_slug_falls_back_to_directory_name(tmp_path):
    """A repo with no remote (e.g. repo: self in a bare workspace) still logs a name."""
    repo = _init_repo(tmp_path / "target")
    assert files_module.__repo_slug__(repo) == "target"


def test_skip_log_line_does_not_leak_credentials(tmp_path, source_dir, capsys):
    (source_dir / "CLAUDE.md").write_text("template\n")
    repo = _init_repo(tmp_path / "target", {"CLAUDE.md": "local\n"})
    repo.create_remote("origin", "https://user:ghs_secrettoken@github.com/org/target.git")

    __check_files__(repo, COMMIT_MSG, [FileConfig(src_file="CLAUDE.md", overwrite=False)])

    out = capsys.readouterr().out
    assert "ghs_secrettoken" not in out
    assert "⏭️" in out
    assert "org/target" in out


# ---------------------------------------------------------------------------
# overwrite: false – core semantics
# ---------------------------------------------------------------------------


def test_overwrite_false_seeds_when_destination_absent(tmp_path, source_dir):
    (source_dir / "CLAUDE.md").write_text("template contents\n")
    repo = _init_repo(tmp_path / "target")

    success, diffs = __check_files__(
        repo,
        COMMIT_MSG,
        [FileConfig(src_file="CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)],
    )

    dest = tmp_path / "target" / "CLAUDE.md"
    assert dest.exists()
    assert dest.read_text() == "template contents\n"
    # A genuine seed is real drift and must be reported as missing.
    assert success is False
    assert "CLAUDE.md" in diffs["missing"]


def test_overwrite_false_leaves_existing_destination_byte_identical(tmp_path, source_dir):
    (source_dir / "CLAUDE.md").write_text("upstream template v2\n")
    local_contents = "locally extended contract\nwith repo-specific guidance\n"
    repo = _init_repo(tmp_path / "target", {"CLAUDE.md": local_contents})
    dest = tmp_path / "target" / "CLAUDE.md"
    before = dest.read_bytes()

    success, diffs = __check_files__(
        repo,
        COMMIT_MSG,
        [FileConfig(src_file="CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)],
    )

    assert dest.read_bytes() == before
    assert dest.read_text() == local_contents
    # Already-seeded is the intended steady state: no drift of any kind.
    assert success is True
    assert diffs is None


def test_overwrite_false_existing_destination_reports_no_drift_for_check_action(tmp_path, source_dir):
    """The `check` action keys off this return value; it must be clean."""
    (source_dir / ".claude-config.yaml").write_text("repo_name: template\n")
    repo = _init_repo(tmp_path / "target", {".claude-config.yaml": "repo_name: consumer\n"})

    success, diffs = __check_files__(
        repo,
        COMMIT_MSG,
        [FileConfig(src_file=".claude-config.yaml", dest_file=".claude-config.yaml", overwrite=False)],
    )

    assert (success, diffs) == (True, None)
    for category in ("missing", "extra", "diff"):
        assert diffs is None or category not in diffs


def test_overwrite_false_ignores_content_differences(tmp_path, source_dir):
    """Existence alone decides -- contents are never compared."""
    (source_dir / "CLAUDE.md").write_text("a" * 500)
    repo = _init_repo(tmp_path / "target", {"CLAUDE.md": "b"})

    success, diffs = __check_files__(
        repo, COMMIT_MSG, [FileConfig(src_file="CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)]
    )

    assert (success, diffs) == (True, None)
    assert (tmp_path / "target" / "CLAUDE.md").read_text() == "b"


# ---------------------------------------------------------------------------
# Regression guard on the default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kwargs", [{}, {"overwrite": True}], ids=["omitted", "explicit-true"])
def test_overwrite_true_replaces_existing_destination(tmp_path, source_dir, kwargs):
    (source_dir / "ci.yml").write_text("new: workflow\n")
    repo = _init_repo(tmp_path / "target", {"ci.yml": "old: workflow\n"})

    success, diffs = __check_files__(repo, COMMIT_MSG, [FileConfig(src_file="ci.yml", dest_file="ci.yml", **kwargs)])

    assert (tmp_path / "target" / "ci.yml").read_text() == "new: workflow\n"
    assert success is False
    assert "ci.yml" in diffs["diff"]


# ---------------------------------------------------------------------------
# No empty commits, branches or PRs
# ---------------------------------------------------------------------------


def test_all_entries_skipped_creates_no_commit(tmp_path, source_dir):
    (source_dir / "CLAUDE.md").write_text("template\n")
    (source_dir / ".claude-config.yaml").write_text("repo_name: template\n")
    repo = _init_repo(
        tmp_path / "target",
        {"CLAUDE.md": "local\n", ".claude-config.yaml": "repo_name: consumer\n"},
    )
    head_before = repo.head.commit.hexsha

    success, diffs = __check_files__(
        repo,
        COMMIT_MSG,
        [
            FileConfig(src_file="CLAUDE.md", dest_file="CLAUDE.md", overwrite=False),
            FileConfig(src_file=".claude-config.yaml", dest_file=".claude-config.yaml", overwrite=False),
        ],
    )

    assert (success, diffs) == (True, None)
    assert repo.head.commit.hexsha == head_before, "no commit should have been created"
    assert files_module.commitChanges is None
    assert files_module.commitCleanup is None
    assert repo.is_dirty(untracked_files=True) is False


def test_no_push_or_pr_when_branch_absent_from_diffs(tmp_path, monkeypatch):
    """With every entry skipped the branch never reaches diffs, so update_files must
    push nothing and open no PR."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _init_repo(workspace / "target")

    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )

    gh_repo = MagicMock()
    gh_repo.name = "target"
    gh_repo.full_name = "org/target"

    errors, messages = update_files(
        gh_repo,
        [BranchFiles(target_branch="main", commit_msg=COMMIT_MSG, files=[])],
        {},  # no drift recorded for "main"
    )

    assert errors == []
    assert messages == []
    gh_repo.create_pull.assert_not_called()
    gh_repo.get_pulls.assert_not_called()


# ---------------------------------------------------------------------------
# Grouping: several file groups sharing one target branch
# ---------------------------------------------------------------------------


def _self_mode_inputs(monkeypatch, workspace, target_dir):
    """Point check_files/update_files at a local repo via the repo: self path."""
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "self",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    monkeypatch.chdir(target_dir)


def _gh_repo(default_branch="main"):
    gh_repo = MagicMock()
    gh_repo.name = "target"
    gh_repo.full_name = "org/target"
    gh_repo.default_branch = default_branch
    gh_repo.owner.login = "org"
    gh_repo.get_pulls.return_value = []
    gh_repo.create_pull.return_value = MagicMock(number=7, html_url="https://github.com/org/target/pull/7")
    return gh_repo


def test_groups_sharing_target_branch_each_get_own_commit(tmp_path, monkeypatch):
    """Two groups on one branch produce two commits, each with its own message."""
    source = tmp_path / "hub"
    source.mkdir()
    (source / "CLAUDE.md").write_text("contract\n")
    (source / "ci.yml").write_text("workflow\n")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source))

    target = tmp_path / "target"
    repo = _init_repo(target)
    _self_mode_inputs(monkeypatch, tmp_path, target)

    success, diffs = check_files(
        _gh_repo(),
        [
            BranchFiles(
                target_branch="main",
                commit_msg="ci(standards): Seed starter files",
                files=[FileConfig(src_file="CLAUDE.md")],
            ),
            BranchFiles(
                target_branch="main",
                commit_msg="chore(workflows): Sync shared CI",
                files=[FileConfig(src_file="ci.yml")],
            ),
        ],
    )

    assert repo.active_branch.name == "repomgr/updates-to-main"
    subjects = [c.message.splitlines()[0] for c in repo.iter_commits("repomgr/updates-to-main")]
    assert any("Seed starter files" in s for s in subjects)
    assert any("Sync shared CI" in s for s in subjects)
    # Each group is its own commit -- neither message absorbs the other's files.
    seed_commit = next(c for c in repo.iter_commits() if "Seed starter files" in c.message)
    ci_commit = next(c for c in repo.iter_commits() if "Sync shared CI" in c.message)
    assert set(seed_commit.stats.files) == {"CLAUDE.md"}
    assert set(ci_commit.stats.files) == {"ci.yml"}

    assert success is False
    assert (target / "CLAUDE.md").exists()
    assert (target / "ci.yml").exists()


def test_group_diffs_are_merged_not_overwritten(tmp_path, monkeypatch):
    """Both groups' files must appear in the single target branch's diff."""
    source = tmp_path / "hub"
    source.mkdir()
    (source / "CLAUDE.md").write_text("contract\n")
    (source / "ci.yml").write_text("workflow\n")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source))

    target = tmp_path / "target"
    _init_repo(target)
    _self_mode_inputs(monkeypatch, tmp_path, target)

    _, diffs = check_files(
        _gh_repo(),
        [
            BranchFiles(target_branch="main", commit_msg="ci(a): one", files=[FileConfig(src_file="CLAUDE.md")]),
            BranchFiles(target_branch="main", commit_msg="ci(b): two", files=[FileConfig(src_file="ci.yml")]),
        ],
    )

    assert set(diffs.keys()) == {"main"}
    assert "CLAUDE.md" in diffs["main"]["missing"]
    assert "ci.yml" in diffs["main"]["missing"], "the first group's diff must not be overwritten"


def test_groups_targeting_different_branches_stay_separate(tmp_path, monkeypatch):
    """Regression guard: distinct target branches still get distinct entries."""
    source = tmp_path / "hub"
    source.mkdir()
    (source / "CLAUDE.md").write_text("contract\n")
    (source / "ci.yml").write_text("workflow\n")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source))

    target = tmp_path / "target"
    repo = _init_repo(target)
    repo.create_head("develop", repo.heads.main.commit)
    _self_mode_inputs(monkeypatch, tmp_path, target)

    _, diffs = check_files(
        _gh_repo(),
        [
            BranchFiles(target_branch="main", commit_msg="ci(a): one", files=[FileConfig(src_file="CLAUDE.md")]),
            BranchFiles(target_branch="develop", commit_msg="ci(b): two", files=[FileConfig(src_file="ci.yml")]),
        ],
    )

    assert set(diffs.keys()) == {"main", "develop"}
    assert "CLAUDE.md" in diffs["main"]["missing"]
    assert "ci.yml" in diffs["develop"]["missing"]


def test_skipped_group_does_not_contribute(tmp_path, monkeypatch):
    source = tmp_path / "hub"
    source.mkdir()
    (source / "CLAUDE.md").write_text("contract\n")
    (source / "ci.yml").write_text("workflow\n")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source))

    target = tmp_path / "target"
    _init_repo(target)
    _self_mode_inputs(monkeypatch, tmp_path, target)

    _, diffs = check_files(
        _gh_repo(),
        [
            BranchFiles(target_branch="main", commit_msg="ci(a): one", files=[FileConfig(src_file="CLAUDE.md")]),
            BranchFiles(
                target_branch="main", commit_msg="ci(b): two", skip=True, files=[FileConfig(src_file="ci.yml")]
            ),
        ],
    )

    assert "CLAUDE.md" in diffs["main"]["missing"]
    assert "ci.yml" not in diffs["main"].get("missing", {})
    assert not (target / "ci.yml").exists()


def test_merge_branch_diffs_sums_metrics_for_shared_path():
    """A path touched by two groups reports the combined change."""
    existing = {"diff": {"shared.md": {"insertions": 2, "deletions": 1, "lines": 3}}}
    merged = files_module.__merge_branch_diffs__(
        existing, {"diff": {"shared.md": {"insertions": 5, "deletions": 0, "lines": 5}}}, "main"
    )
    assert merged["diff"]["shared.md"] == {"insertions": 7, "deletions": 1, "lines": 8}


def test_merge_branch_diffs_returns_new_when_no_existing():
    new = {"missing": {"a.md": {"insertions": 1, "deletions": 0, "lines": 1}}}
    assert files_module.__merge_branch_diffs__(None, new, "main") is new


# ---------------------------------------------------------------------------
# Grouping: one push and one PR per target branch
# ---------------------------------------------------------------------------


def _workspace_with_sync_branch(tmp_path, files=None):
    """A workspace clone sitting on a sync branch, with a pushable bare origin."""
    origin = tmp_path / "origin.git"
    Repo.init(origin, bare=True, initial_branch="main")

    work = tmp_path / "ws" / "target"
    repo = _init_repo(work, files)
    repo.create_remote("origin", str(origin))
    repo.remotes.origin.push("main")
    repo.create_head("repomgr/updates-to-main").checkout()
    (work / "CLAUDE.md").write_text("seeded\n")
    repo.git.add("-A")
    repo.index.commit("ci(standards-update): Seed starter files")
    return tmp_path / "ws", repo


def test_update_files_opens_one_pr_for_multiple_groups(tmp_path, monkeypatch):
    workspace, _ = _workspace_with_sync_branch(tmp_path)
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    gh_repo = _gh_repo()
    diffs = {"main": {"missing": {"CLAUDE.md": {"insertions": 1, "deletions": 0, "lines": 1}}}}

    errors, messages = update_files(
        gh_repo,
        [
            BranchFiles(target_branch="main", commit_msg="ci(standards): Seed starter files"),
            BranchFiles(target_branch="main", commit_msg="chore(workflows): Sync shared CI"),
        ],
        diffs,
    )

    assert errors == []
    # Two groups, one shared sync branch -> exactly one PR and one summary line.
    assert gh_repo.create_pull.call_count == 1
    assert len(messages) == 1


def test_pr_title_uses_configured_value(tmp_path, monkeypatch):
    workspace, _ = _workspace_with_sync_branch(tmp_path)
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    gh_repo = _gh_repo()
    diffs = {"main": {"missing": {"CLAUDE.md": {"insertions": 1, "deletions": 0, "lines": 1}}}}

    update_files(
        gh_repo,
        [
            BranchFiles(target_branch="main", commit_msg="ci(a): one", pr_title="chore(sync): Apply org standards"),
            BranchFiles(target_branch="main", commit_msg="ci(b): two"),
        ],
        diffs,
    )

    assert gh_repo.create_pull.call_args.kwargs["title"] == "chore(sync): Apply org standards"


def test_pr_title_falls_back_to_latest_commit_subject(tmp_path, monkeypatch):
    workspace, _ = _workspace_with_sync_branch(tmp_path)
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    gh_repo = _gh_repo()
    diffs = {"main": {"missing": {"CLAUDE.md": {"insertions": 1, "deletions": 0, "lines": 1}}}}

    update_files(gh_repo, [BranchFiles(target_branch="main", commit_msg="ci(a): one")], diffs)

    assert gh_repo.create_pull.call_args.kwargs["title"] == "ci(standards-update): Seed starter files"


def test_existing_pr_title_only_rewritten_when_configured(tmp_path, monkeypatch):
    """An unconfigured title must not churn an open PR's title on every run."""
    workspace, _ = _workspace_with_sync_branch(tmp_path)
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    existing_pr = MagicMock(number=3, html_url="https://github.com/org/target/pull/3")
    gh_repo = _gh_repo()
    gh_repo.get_pulls.return_value = [existing_pr]
    diffs = {"main": {"missing": {"CLAUDE.md": {"insertions": 1, "deletions": 0, "lines": 1}}}}

    update_files(gh_repo, [BranchFiles(target_branch="main", commit_msg="ci(a): one")], diffs)

    assert "title" not in existing_pr.edit.call_args.kwargs


def test_existing_pr_title_updated_when_configured(tmp_path, monkeypatch):
    workspace, _ = _workspace_with_sync_branch(tmp_path)
    monkeypatch.setattr(
        files_module,
        "get_inputs",
        lambda: {
            "repo": "org/target",
            "workspace_path": str(workspace),
            "github_server_url": "https://github.com",
        },
    )
    existing_pr = MagicMock(number=3, html_url="https://github.com/org/target/pull/3")
    gh_repo = _gh_repo()
    gh_repo.get_pulls.return_value = [existing_pr]
    diffs = {"main": {"missing": {"CLAUDE.md": {"insertions": 1, "deletions": 0, "lines": 1}}}}

    update_files(
        gh_repo,
        [BranchFiles(target_branch="main", commit_msg="ci(a): one", pr_title="chore(sync): Apply org standards")],
        diffs,
    )

    assert existing_pr.edit.call_args.kwargs["title"] == "chore(sync): Apply org standards"


def test_configured_pr_title_conflict_warns_and_takes_first(capsys):
    branches = [
        BranchFiles(target_branch="main", pr_title="first title"),
        BranchFiles(target_branch="main", pr_title="second title"),
    ]
    assert files_module.__configured_pr_title__(branches, "main") == "first title"
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "second title" in out


def test_configured_pr_title_ignores_skipped_and_other_branches():
    branches = [
        BranchFiles(target_branch="main", skip=True, pr_title="skipped title"),
        BranchFiles(target_branch="develop", pr_title="other branch title"),
        BranchFiles(target_branch="main", pr_title="wanted title"),
    ]
    assert files_module.__configured_pr_title__(branches, "main") == "wanted title"
    assert files_module.__configured_pr_title__(branches, "release") is None


# ---------------------------------------------------------------------------
# Interaction with the synced-from-sha skip logic
# ---------------------------------------------------------------------------


def test_seeding_still_records_source_sha_marker(tmp_path, monkeypatch):
    """A file seeded on its first run must record its source SHA like any other copy,
    so the existing idempotency machinery keeps working."""
    source_repo_dir = tmp_path / "hub"
    _init_repo(source_repo_dir, {"templates/CLAUDE.md": "template\n"})
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source_repo_dir))
    repo = _init_repo(tmp_path / "target")

    success, _ = __check_files__(
        repo,
        COMMIT_MSG,
        [FileConfig(src_file="templates/CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)],
    )

    assert success is False  # the seed itself is drift
    assert files_module.commitChanges is not None
    assert _SYNC_SHA_MARKER in files_module.commitChanges.message


def test_skipped_seed_does_not_record_source_sha(tmp_path, monkeypatch):
    """A skipped file must not contribute its SHA to the commit message -- that would
    claim a sync that never happened."""
    source_repo_dir = tmp_path / "hub"
    hub = _init_repo(source_repo_dir, {"templates/CLAUDE.md": "template\n"})
    # Commit ci.yml separately: a source SHA identifies a commit, not a file, so files
    # committed together would share one SHA and this test could not tell them apart.
    (source_repo_dir / "ci.yml").write_text("new\n")
    hub.git.add("-A")
    hub.index.commit("add ci")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source_repo_dir))
    repo = _init_repo(tmp_path / "target", {"CLAUDE.md": "local\n", "ci.yml": "old\n"})

    source_sha = files_module.__get_source_file_sha__(source_repo_dir / "templates" / "CLAUDE.md")
    assert source_sha is not None

    __check_files__(
        repo,
        COMMIT_MSG,
        [
            FileConfig(src_file="templates/CLAUDE.md", dest_file="CLAUDE.md", overwrite=False),
            FileConfig(src_file="ci.yml", dest_file="ci.yml"),  # managed, forces a commit
        ],
    )

    assert files_module.commitChanges is not None, "the managed file should still commit"
    assert source_sha not in files_module.commitChanges.message
    assert (tmp_path / "target" / "CLAUDE.md").read_text() == "local\n"
    assert (tmp_path / "target" / "ci.yml").read_text() == "new\n"


def test_seed_ignores_sha_history_when_destination_absent(tmp_path, monkeypatch):
    """A seed whose source SHA is already in branch history -- because a sibling file
    committed alongside it was synced -- must still be written when it is absent.
    Source SHAs identify commits, not files, so history must not gate a seed."""
    source_repo_dir = tmp_path / "hub"
    # Both files land in one commit, so they share a single source SHA.
    _init_repo(source_repo_dir, {"templates/CLAUDE.md": "template\n", "ci.yml": "v1\n"})
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source_repo_dir))
    repo = _init_repo(tmp_path / "target")

    # First run syncs the managed file, recording the shared SHA in branch history.
    __check_files__(repo, COMMIT_MSG, [FileConfig(src_file="ci.yml", dest_file="ci.yml")])
    shared_sha = files_module.__get_source_file_sha__(source_repo_dir / "ci.yml")
    assert files_module.__has_source_sha_in_history__(repo, repo.active_branch.name, shared_sha)

    # Second run seeds CLAUDE.md, which has never been written to the target.
    files_module.commitChanges = None
    __check_files__(
        repo,
        COMMIT_MSG,
        [FileConfig(src_file="templates/CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)],
    )

    dest = tmp_path / "target" / "CLAUDE.md"
    assert dest.exists(), "seed must not be suppressed by a sibling file's SHA marker"
    assert dest.read_text() == "template\n"


def test_sha_skip_still_applies_to_managed_files(tmp_path, monkeypatch):
    """Regression guard: the synced-from-sha skip is untouched for overwrite: true."""
    source_repo_dir = tmp_path / "hub"
    _init_repo(source_repo_dir, {"ci.yml": "v1\n"})
    monkeypatch.setenv("GITHUB_WORKSPACE", str(source_repo_dir))
    repo = _init_repo(tmp_path / "target")

    config = [FileConfig(src_file="ci.yml", dest_file="ci.yml")]

    first_success, _ = __check_files__(repo, COMMIT_MSG, config)
    assert first_success is False  # copied on the first run

    files_module.commitChanges = None
    second_success, second_diffs = __check_files__(repo, COMMIT_MSG, config)

    # Source unchanged and its SHA is now in branch history -> skipped entirely.
    assert (second_success, second_diffs) == (True, None)
    assert files_module.commitChanges is None
