"""Repo root / `.pm.toml` discovery."""

from __future__ import annotations

from pathlib import Path

from src.claude_pm.infrastructure.repo_detect import (
    find_pm_file,
    find_repo_root,
)


def _make_repo(tmp_path: Path, name: str = "my-repo") -> Path:
    root = tmp_path / name
    (root / "src" / "deep").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


class TestFindRepoRoot:
    def test_finds_root_from_the_root_itself(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert find_repo_root(root) == root

    def test_finds_root_from_a_nested_subdirectory(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert find_repo_root(root / "src" / "deep") == root

    def test_git_as_a_file_counts_as_a_root(self, tmp_path: Path) -> None:
        """Worktrees and submodules have a `.git` file, not a directory."""
        root = tmp_path / "worktree"
        (root / "src").mkdir(parents=True)
        (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")
        assert find_repo_root(root / "src") == root

    def test_returns_none_outside_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert find_repo_root(plain) is None


class TestFindPmFile:
    def test_finds_pm_file_at_the_root_from_a_subdirectory(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        pm_file = root / ".pm.toml"
        pm_file.write_text("version = 1\n", encoding="utf-8")
        assert find_pm_file(root / "src" / "deep") == pm_file

    def test_prefers_the_nearest_pm_file(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        (root / ".pm.toml").write_text("version = 1\n", encoding="utf-8")
        nearer = root / "src" / ".pm.toml"
        nearer.write_text("version = 1\n", encoding="utf-8")
        assert find_pm_file(root / "src" / "deep") == nearer

    def test_does_not_escape_the_repo_root(self, tmp_path: Path) -> None:
        """A `.pm.toml` above the repo belongs to another project — never inherit it."""
        (tmp_path / ".pm.toml").write_text("version = 1\n", encoding="utf-8")
        root = _make_repo(tmp_path)
        assert find_pm_file(root / "src") is None

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert find_pm_file(root) is None
