from unittest.mock import MagicMock

from repo_manager.gh.labels import update_labels
from repo_manager.schemas import Label


def _make_repo(existing_names):
    """Builds a mock Repository whose get_label returns a fresh mock label for names in
    ``existing_names`` and raises for anything else (mirroring PyGithub's behaviour)."""
    labels = {name: MagicMock(name=name, color="ffffff", description="") for name in existing_names}

    def get_label(name):
        if name in labels:
            return labels[name]
        raise Exception(f"Label {name} not found")

    repo = MagicMock()
    repo.get_label.side_effect = get_label
    return repo, labels


def test_rename_to_existing_name_deletes_old_label():
    # "old" is being renamed to "new", but "new" already exists in the repo.
    label = Label(name="old", new_name="new", color="ff00ff")
    diffs = {"diff": {"old": {"name": {"expected": "new", "found": "old"}}}}
    repo, labels = _make_repo(existing_names=["old", "new"])

    errors, _ = update_labels(repo, [label], diffs)

    assert errors == []
    # The old label is deleted; the surviving "new" label is left untouched.
    labels["old"].delete.assert_called_once()
    labels["old"].edit.assert_not_called()
    labels["new"].delete.assert_not_called()
    labels["new"].edit.assert_not_called()


def test_rename_to_free_name_edits_label():
    # "old" is being renamed to "new", and "new" does not already exist -> normal edit/rename.
    label = Label(name="old", new_name="new", color="ff00ff")
    diffs = {"diff": {"old": {"name": {"expected": "new", "found": "old"}}}}
    repo, labels = _make_repo(existing_names=["old"])

    errors, _ = update_labels(repo, [label], diffs)

    assert errors == []
    labels["old"].edit.assert_called_once()
    # The target name is the first positional arg to edit().
    assert labels["old"].edit.call_args.args[0] == "new"
    labels["old"].delete.assert_not_called()


def test_non_rename_diff_edits_label():
    # No rename (name == expected_name), just a color change -> edit, never delete.
    label = Label(name="keep", color="00ff00")
    diffs = {"diff": {"keep": {"color": {"expected": "00ff00", "found": "ffffff"}}}}
    repo, labels = _make_repo(existing_names=["keep"])

    errors, _ = update_labels(repo, [label], diffs)

    assert errors == []
    labels["keep"].edit.assert_called_once()
    labels["keep"].delete.assert_not_called()


def test_rename_to_existing_name_delete_failure_is_reported():
    label = Label(name="old", new_name="new", color="ff00ff")
    diffs = {"diff": {"old": {"name": {"expected": "new", "found": "old"}}}}
    repo, labels = _make_repo(existing_names=["old", "new"])
    labels["old"].delete.side_effect = Exception("boom")

    errors, _ = update_labels(repo, [label], diffs)

    assert len(errors) == 1
    assert errors[0]["type"] == "label-delete"
    assert errors[0]["name"] == "old"
