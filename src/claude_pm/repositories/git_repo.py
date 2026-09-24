"""Locate the repo root and its `.pm.toml`.

The repo root — not the cwd basename — is the identity of a project. Two checkouts
named `api` in different directories are different repos, and `pm` run from a
subdirectory is still the same repo.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..config import PM_FILE_NAME


def _iter_up(start: Path) -> Iterator[Path]:
    current = start.resolve()
    yield current
    yield from current.parents


def find_repo_root(start: Path | None = None) -> Path | None:
    """Return the directory holding `.git`, or None outside a repo.

    `.git` is a directory in a normal clone and a file in a worktree or submodule,
    so we test for existence rather than for a directory.
    """
    for directory in _iter_up(start or Path.cwd()):
        if (directory / ".git").exists():
            return directory
    return None


def find_pm_file(start: Path | None = None) -> Path | None:
    """Return the nearest `.pm.toml` at or above `start`, never above the repo root.

    Stopping at the repo root is deliberate: a `.pm.toml` in a parent directory
    belongs to a different project, and inheriting it would bind this repo to a
    board nobody declared for it.
    """
    begin = (start or Path.cwd()).resolve()
    root = find_repo_root(begin)
    for directory in _iter_up(begin):
        candidate = directory / PM_FILE_NAME
        if candidate.is_file():
            return candidate
        if root is not None and directory == root:
            break
    return None
