"""The repo root, not the cwd basename, is a project's identity."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..config import PM_FILE_NAME


def _iter_up(start: Path) -> Iterator[Path]:
    current = start.resolve()
    yield current
    yield from current.parents


def find_repo_root(start: Path | None = None) -> Path | None:
    """`.git` is a file in a worktree or submodule, so this checks existence, not is_dir."""
    for directory in _iter_up(start or Path.cwd()):
        if (directory / ".git").exists():
            return directory

    return None


def find_pm_file(start: Path | None = None) -> Path | None:
    """Never looks above the repo root: a parent's `.pm.toml` belongs to a different project."""
    begin = (start or Path.cwd()).resolve()
    root = find_repo_root(begin)
    for directory in _iter_up(begin):
        candidate = directory / PM_FILE_NAME
        if candidate.is_file():
            return candidate
        if root is not None and directory == root:
            break

    return None
