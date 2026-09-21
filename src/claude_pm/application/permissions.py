"""Register the permissions the skill needs in `~/.claude/settings.json`.

This is the one place pm writes outside the repo and the tracker, and it widens
what Claude Code may run without asking. It used to happen as a silent side
effect of `pm setup`; now it only happens when someone asks for it, and it can
be previewed first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_PERMISSIONS = [
    "Bash(pm:*)",
    "Write(~/.claude/tmp_*.md)",
]


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def missing_permissions(path: Path | None = None) -> list[str]:
    """Which required entries are not in the allow list yet."""
    settings = _read(path or settings_path())
    allow = settings.get("permissions", {}).get("allow", [])
    allow_set = set(allow) if isinstance(allow, list) else set()
    return [entry for entry in REQUIRED_PERMISSIONS if entry not in allow_set]


def register_permissions(path: Path | None = None) -> list[str]:
    """Add the missing entries. Returns what was added (empty if nothing was)."""
    target = path or settings_path()
    missing = missing_permissions(target)
    if not missing:
        return []

    settings = _read(target)
    perms = settings.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    if not isinstance(allow, list):
        raise ValueError(f"{target}: permissions.allow is not a list.")
    allow.extend(missing)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return missing


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
