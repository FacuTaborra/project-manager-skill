"""The one place pm writes outside the repo and the tracker, so it only runs when asked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings_path
from ..exceptions import ConfigError

REQUIRED_PERMISSIONS = [
    "Bash(pm:*)",
    "Write(~/.claude/tmp_*.md)",
]


def missing_permissions(path: Path | None = None) -> list[str]:
    settings = _read(path or settings_path())
    allow = settings.get("permissions", {}).get("allow", [])
    granted = set(allow) if isinstance(allow, list) else set()

    return [entry for entry in REQUIRED_PERMISSIONS if entry not in granted]


def register_permissions(path: Path | None = None) -> tuple[list[str], list[str]]:
    """Returns (added, still_missing), read back from disk: Claude Code rewrites this file while
    running, and a concurrent save can drop what was just appended.
    """
    target = path or settings_path()
    missing = missing_permissions(target)
    if not missing:
        return [], []

    settings = _read(target, strict=True)
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    if not isinstance(allow, list):
        raise ConfigError(f"{target}: permissions.allow is not a list. Fix it by hand and re-run.")
    allow.extend(missing)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    still_missing = missing_permissions(target)

    return [entry for entry in missing if entry not in still_missing], still_missing


def _read(path: Path, *, strict: bool = False) -> dict[str, Any]:
    """`strict` is for the write path: rewriting a file we could not parse would wipe it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        if strict:
            raise ConfigError(
                f"{path} is not valid JSON ({exc}). Fix it by hand and re-run."
            ) from exc
        return {}
    if isinstance(data, dict):
        return data
    if strict:
        raise ConfigError(f"{path} does not hold a JSON object. Fix it by hand and re-run.")

    return {}
