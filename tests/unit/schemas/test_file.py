import random
import string
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from repo_manager.schemas.file import FileConfig, parse_remote_path


VALID_CONFIG = {
    "src_file": "tests/unit/schemas/test_file.py",
    "dest_file": "test",
}


def test_file_valid_config():
    this_file_config = FileConfig(**VALID_CONFIG)
    assert this_file_config.src_file == Path(VALID_CONFIG["src_file"])
    assert this_file_config.dest_file == Path(VALID_CONFIG["dest_file"])
    assert this_file_config.move is False
    assert this_file_config.exists
    assert this_file_config.src_file_exists
    assert this_file_config.remote_src is False
    assert this_file_config.overwrite is True


def test_file_src_file_exists():
    this_file_config = FileConfig(**VALID_CONFIG)
    assert this_file_config.src_file_exists

    missing_file = deepcopy(VALID_CONFIG)
    missing_file["src_file"] = "".join(random.choices(string.ascii_lowercase, k=16))
    missing_file_config = FileConfig(**missing_file)
    assert missing_file_config.src_file_exists is False
    with pytest.raises(ValueError):
        missing_file_config.src_file_contents

    executable_file = deepcopy(VALID_CONFIG)
    executable_file["src_file"] = "./.github/scripts/replace_inputs.sh"
    executable_config = FileConfig(**executable_file)
    assert executable_config.src_file_exists


def test_file_args_validation():
    invalid_config = deepcopy(VALID_CONFIG)
    invalid_config["src_file"] = None
    with pytest.raises(ValidationError):
        FileConfig(**invalid_config)
    invalid_config = deepcopy(VALID_CONFIG)
    invalid_config["dest_file"] = None
    with pytest.raises(ValidationError):
        FileConfig(**invalid_config)


def test_delete_only_with_dest_file():
    """exists=False with dest_file and no src_file should pass validation."""
    config = FileConfig(exists=False, dest_file="some/path/to/file.txt")
    assert config.exists is False
    assert config.dest_file == Path("some/path/to/file.txt")
    assert config.src_file is None


def test_delete_only_without_dest_file_fails():
    """exists=False with neither src_file nor dest_file should fail validation."""
    with pytest.raises(ValidationError):
        FileConfig(exists=False)


def test_example_works():
    with open("examples/settings.yml") as fh:
        example_data = yaml.safe_load(fh)

    assert len(example_data["batch_file_operations"]) > 0
    for file_config_dict in example_data["batch_file_operations"][0]["files"]:
        FileConfig(**file_config_dict)


# ---------------------------------------------------------------------------
# overwrite / copy-once – unit tests
# ---------------------------------------------------------------------------


def test_overwrite_defaults_to_true_when_omitted():
    """Omitting overwrite must preserve the pre-existing destructive-copy default."""
    assert FileConfig(**VALID_CONFIG).overwrite is True


@pytest.mark.parametrize("value", [True, False])
def test_overwrite_roundtrips(value):
    config = deepcopy(VALID_CONFIG)
    config["overwrite"] = value
    assert FileConfig(**config).overwrite is value


def test_unknown_key_rejected():
    """extra='forbid': an unrecognised key must fail rather than silently degrade."""
    typo = deepcopy(VALID_CONFIG)
    typo["overwite"] = False  # note the typo
    with pytest.raises(ValidationError):
        FileConfig(**typo)


def test_unknown_key_rejected_names_the_offending_field():
    """The validation error should point at the key so a typo is diagnosable."""
    typo = deepcopy(VALID_CONFIG)
    typo["mode"] = "100755"
    with pytest.raises(ValidationError, match="mode"):
        FileConfig(**typo)


def test_overwrite_false_with_exists_false_rejected():
    """Seeding a file we are deleting is incoherent."""
    with pytest.raises(ValidationError, match="meaningless"):
        FileConfig(exists=False, dest_file="some/file.txt", overwrite=False)


def test_overwrite_false_with_move_true_rejected():
    """A skipped move would leave src_file in place and copy nothing."""
    with pytest.raises(ValidationError, match="cannot be combined with move"):
        FileConfig(src_file="remote://old.txt", dest_file="new.txt", move=True, overwrite=False)


def test_overwrite_false_with_move_false_is_fine():
    """The move guard must not reject the ordinary copy-once case."""
    cfg = FileConfig(src_file="templates/CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)
    assert cfg.overwrite is False
    assert cfg.move is False


def test_overwrite_false_permitted_on_remote_copy():
    """remote:// copies (not moves) may still be declared copy-once."""
    cfg = FileConfig(src_file="remote://templates/CLAUDE.md", dest_file="CLAUDE.md", overwrite=False)
    assert cfg.remote_src is True
    assert cfg.overwrite is False


# ---------------------------------------------------------------------------
# parse_remote_path – unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("remote://path/to/file.txt", Path("path/to/file.txt")),
        ("remote://single.md", Path("single.md")),
        ("remote://dir/sub/file", Path("dir/sub/file")),
    ],
)
def test_parse_remote_path_valid(value, expected):
    """Canonical remote:// paths should be accepted and normalised."""
    assert parse_remote_path(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "remote:foo.txt",  # missing //
        "remote:///abs.txt",  # absolute path after stripping scheme
        "remote://",  # empty path component
        "remote://../outside",  # traversal
        "remote://../up/file",  # traversal via parent segment
    ],
)
def test_parse_remote_path_malformed(value):
    """Malformed remote paths should raise ValueError."""
    with pytest.raises(ValueError):
        parse_remote_path(value)


# ---------------------------------------------------------------------------
# FileConfig – remote:// integration
# ---------------------------------------------------------------------------


def test_fileconfig_remote_prefix_sets_remote_src():
    """A remote:// src_file should set remote_src=True automatically."""
    cfg = FileConfig(src_file="remote://old/path.txt", dest_file="new/path.txt")
    assert cfg.src_file == Path("old/path.txt")
    assert cfg.remote_src is True


def test_fileconfig_malformed_remote_prefix_raises():
    """remote:foo (missing //) in src_file should raise a ValidationError."""
    with pytest.raises(ValidationError):
        FileConfig(src_file="remote:foo.txt", dest_file="bar.txt")


def test_fileconfig_remote_empty_path_raises():
    """remote:// with no path after the scheme should raise a ValidationError."""
    with pytest.raises(ValidationError):
        FileConfig(src_file="remote://", dest_file="bar.txt")


def test_fileconfig_remote_absolute_path_raises():
    """remote:/// (absolute path after stripping scheme) should raise a ValidationError."""
    with pytest.raises(ValidationError):
        FileConfig(src_file="remote:///absolute.txt", dest_file="bar.txt")


def test_fileconfig_remote_traversal_raises():
    """remote://../ (path traversal) should raise a ValidationError."""
    with pytest.raises(ValidationError):
        FileConfig(src_file="remote://../secret", dest_file="bar.txt")
