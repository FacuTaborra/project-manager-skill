"""Obsidian vault context provider.

Reads `proyectos/<repo>/STATUS.md` from the configured vault path. The format
is conventional (frontmatter + sections); we only return a truncated excerpt.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VAULT = Path.home() / ".claude-memory"


def vault_path_from_env() -> Path | None:
    """Resolve the configured vault path, or None when it does not exist on disk."""
    env = os.environ.get("CLAUDE_MEMORY_PATH")
    path = Path(env).expanduser() if env else DEFAULT_VAULT
    return path if path.is_dir() else None


class ObsidianVaultContext:
    """Implements ContextProvider against an Obsidian vault on disk."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path

    def is_available(self) -> bool:
        return self.vault_path.is_dir()

    def get_status_excerpt(self, repo_name: str, max_chars: int = 1500) -> str | None:
        if not self.is_available():
            return None
        status_file = self.vault_path / "proyectos" / repo_name / "STATUS.md"
        if not status_file.is_file():
            return None
        try:
            text = status_file.read_text(encoding="utf-8")
        except OSError:
            return None
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[... truncated ...]"
