"""`install-skill` — put SKILL.md where Claude Code looks for it.

Installed with `uv tool install`, the repo does not exist on disk, so SKILL.md
travels as package data and is read through importlib.resources rather than from
a path next to the source.
"""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path

from ..config import SKILL_DIR, SKILL_FILE, settings_path
from ..exceptions import EXIT_OK, PMError
from ..repositories.claude_settings_repository import (
    missing_permissions as list_missing_permissions,
)
from ..repositories.claude_settings_repository import register_permissions
from ..services.next_step import next_step
from ._output import print_json


def run(args: argparse.Namespace) -> int:
    skill_markdown = _skill_markdown()
    missing_permissions = list_missing_permissions()

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "would_write": str(SKILL_FILE),
                "would_add_permissions": missing_permissions,
                "settings": str(settings_path()),
            }
        )
        return EXIT_OK

    if missing_permissions and not args.yes and not args.skip_permissions:
        raise PMError(
            f"This would widen what Claude Code may run without asking, by adding "
            f"{', '.join(missing_permissions)} to {settings_path()}.\n"
            f"Re-run with --yes to accept, or --skip-permissions to install only SKILL.md."
        )

    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_FILE.write_text(skill_markdown, encoding="utf-8")

    added: list[str] = []
    still_missing: list[str] = []
    if not args.skip_permissions:
        added, still_missing = register_permissions()

    payload: dict[str, object] = {
        "ok": True,
        "installed": str(SKILL_FILE),
        "permissions_added": added,
    }
    if still_missing:
        payload["permissions_not_applied"] = still_missing
        payload["why"] = (
            f"Claude Code rewrote {settings_path()} while this ran and dropped them. "
            f"Re-run this command, or add them from Claude Code with /permissions."
        )
    print_json(payload)
    print(next_step().render(), file=sys.stderr)
    return EXIT_OK


def _skill_markdown() -> str:
    try:
        return (resources.files("claude_pm") / "_skill" / "SKILL.md").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass

    # Running from a source checkout, where the file has not been packaged yet.
    source = Path(__file__).resolve().parents[3] / "SKILL.md"
    if source.is_file():
        return source.read_text(encoding="utf-8")

    raise PMError(
        "SKILL.md is missing from the installed package. Reinstall with "
        "`uv tool install --force git+https://github.com/FacuTaborra/claude-pm-skill`."
    )
