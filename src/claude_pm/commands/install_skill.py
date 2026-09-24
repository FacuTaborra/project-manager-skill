"""`install-skill` — installed with `uv tool install` the repo is not on disk, so SKILL.md travels
as package data and is read through importlib.resources."""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path

from ..config import SKILL_DIR, SKILL_FILE, settings_path
from ..exceptions import EXIT_OK, PMError
from ..repositories.claude_settings_repository import missing_permissions, register_permissions
from ..services.next_step import next_step
from ._output import print_json


def run(args: argparse.Namespace) -> int:
    skill_markdown = _skill_markdown()
    permissions_to_add = missing_permissions()

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "would_write": str(SKILL_FILE),
                "would_add_permissions": permissions_to_add,
                "settings": str(settings_path()),
            }
        )
        return EXIT_OK

    if permissions_to_add and not args.yes and not args.skip_permissions:
        raise PMError(
            f"This would widen what Claude Code may run without asking, by adding "
            f"{', '.join(permissions_to_add)} to {settings_path()}.\n"
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
    """Falls back to the repo's SKILL.md when running from a source checkout, where it is not
    packaged yet."""
    try:
        return (resources.files("claude_pm") / "_skill" / "SKILL.md").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass

    source = Path(__file__).resolve().parents[3] / "SKILL.md"
    if source.is_file():
        return source.read_text(encoding="utf-8")

    raise PMError(
        "SKILL.md is missing from the installed package. Reinstall with "
        "`uv tool install --force git+https://github.com/FacuTaborra/claude-pm-skill`."
    )
