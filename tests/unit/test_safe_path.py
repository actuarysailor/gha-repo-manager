"""Tests for the _safe_path path-containment utility in repo_manager.gh.files."""

import pytest
from pathlib import Path

from repo_manager.gh.files import _safe_path, _select_repo_delete_target
from repo_manager.schemas.file import FileConfig


class TestSafePathValid:
    """_safe_path should return a resolved path for legitimate inputs."""

    def test_simple_relative_file(self, tmp_path):
        result = _safe_path(tmp_path, Path("some/file.txt"))
        assert result == tmp_path.resolve() / "some" / "file.txt"

    def test_nested_path(self, tmp_path):
        result = _safe_path(tmp_path, Path("a/b/c/d.py"))
        assert result == tmp_path.resolve() / "a" / "b" / "c" / "d.py"

    def test_base_itself(self, tmp_path):
        """Joining an empty relative path should return the base itself."""
        result = _safe_path(tmp_path, Path("."))
        assert result == tmp_path.resolve()

    def test_base_filename_only(self, tmp_path):
        result = _safe_path(tmp_path, Path("file.txt"))
        assert result == tmp_path.resolve() / "file.txt"

    def test_path_with_redundant_dot(self, tmp_path):
        """Paths containing ./ should still resolve cleanly within base."""
        result = _safe_path(tmp_path, Path("./subdir/file.txt"))
        assert result == tmp_path.resolve() / "subdir" / "file.txt"

    def test_symlink_inside_base(self, tmp_path):
        """A symlink that resolves to a path still inside base should be allowed."""
        target = tmp_path / "real_dir"
        target.mkdir()
        link = tmp_path / "link_dir"
        link.symlink_to(target)
        result = _safe_path(tmp_path, Path("link_dir/file.txt"))
        assert result == target.resolve() / "file.txt"
        assert result.is_relative_to(tmp_path.resolve())


class TestSafePathTraversal:
    """_safe_path must reject paths that escape the base directory."""

    def test_double_dot_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="outside the repo root"):
            _safe_path(tmp_path, Path("../escape.txt"))

    def test_deep_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="outside the repo root"):
            _safe_path(tmp_path, Path("a/b/../../../../../../etc/passwd"))

    def test_absolute_path_outside_base(self, tmp_path):
        """An absolute path that is outside base should be rejected.

        Path division: ``base / Path('/outside')`` discards ``base`` because
        Path('/outside') is absolute, so the resolved result escapes the root.
        """
        with pytest.raises(ValueError, match="outside the repo root"):
            _safe_path(tmp_path, Path("/etc/passwd"))

    def test_absolute_path_inside_base(self, tmp_path):
        """An absolute path that happens to be inside base should be allowed."""
        inner = tmp_path / "subdir" / "file.txt"
        result = _safe_path(tmp_path, inner)
        assert result == inner.resolve()

    def test_symlink_escaping_base(self, tmp_path):
        """A symlink whose target is outside the base must be rejected."""
        outside = tmp_path.parent  # guaranteed to be outside tmp_path
        link = tmp_path / "evil_link"
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="outside the repo root"):
            _safe_path(tmp_path, Path("evil_link"))

    def test_null_byte_in_path(self, tmp_path):
        """Paths with null bytes cause an OS error before containment check."""
        with pytest.raises((ValueError, OSError)):
            _safe_path(tmp_path, Path("file\x00.txt"))

    def test_error_message_includes_paths(self, tmp_path):
        """ValueError message should name both the bad path and the root."""
        with pytest.raises(ValueError) as exc_info:
            _safe_path(tmp_path, Path("../outside"))
        msg = str(exc_info.value)
        assert "outside the repo root" in msg
        assert str(tmp_path.resolve()) in msg


class TestDeleteTargetSelection:
    def test_delete_prefers_dest_file(self, tmp_path):
        cfg = FileConfig(src_file="remote://old.txt", dest_file=Path("new.txt"), exists=False, move=True)
        assert _select_repo_delete_target(tmp_path, cfg) == tmp_path.resolve() / "new.txt"

    def test_delete_falls_back_to_repo_internal_remote_src_only(self, tmp_path):
        cfg = FileConfig(src_file="remote://old.txt", dest_file=Path("/outside/delete.txt"), exists=False, move=True)
        assert _select_repo_delete_target(tmp_path, cfg) == tmp_path.resolve() / "old.txt"

    def test_delete_does_not_use_local_src_as_fallback(self, tmp_path):
        cfg = FileConfig(
            src_file=Path("/outside/source.txt"), dest_file=Path("/outside/delete.txt"), exists=False, move=True
        )
        assert _select_repo_delete_target(tmp_path, cfg) is None
