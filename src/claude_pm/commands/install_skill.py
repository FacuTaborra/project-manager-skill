"""`install-skill` — put SKILL.md where Claude Code looks for it.

Installed with `uv tool install`, the repo does not exist on disk, so SKILL.md
travels as package data and is read through importlib.resources rather than from
a path next to the source.
"""

from __future__ import annotations

import argparse
from importlib import resources
from pathlib import Path

from ..application.onboarding import SKILL_DIR, next_step
from ..application.permissions import missing_permissions, register_permissions, settings_path
from ..exceptions import EXIT_OK, PMError
from ._helpers import print_json

SKILL_TARGET = SKILL_DIR / "SKILL.md"


def run(args: argparse.Namespace) -> int:
    content = _skill_markdown()
    pending = missing_permissions()
    junction = _junction_target()

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "would_write": str(SKILL_TARGET),
                "would_add_permissions": pending,
                "settings": str(settings_path()),
                "legacy_junction": str(junction) if junction else None,
            }
        )
        return EXIT_OK

    if junction:
        raise PMError(
            f"{SKILL_DIR} is a link to {junction}, left behind by the old install script.\n"
            f"The 'installed' skill would be a working tree that changes as you develop, and "
            f"writing here would touch that checkout.\n"
            f"Remove the link first, then re-run:\n"
            f'  Windows:      rmdir "{SKILL_DIR}"\n'
            f'  Linux/macOS:  rm "{SKILL_DIR}"'
        )

    if pending and not args.yes and not args.skip_permissions:
        raise PMError(
            f"This would widen what Claude Code may run without asking, by adding "
            f"{', '.join(pending)} to {settings_path()}.\n"
            f"Re-run with --yes to accept, or --skip-permissions to install only SKILL.md."
        )

    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_TARGET.write_text(content, encoding="utf-8")
    added = [] if args.skip_permissions else register_permissions()

    print_json({"ok": True, "installed": str(SKILL_TARGET), "permissions_added": added})
    print(next_step().render())
    return EXIT_OK


def _junction_target() -> Path | None:
    """The clone a legacy symlink/junction points at, if that is what SKILL_DIR is."""
    if not SKILL_DIR.exists():
        return None
    resolved = SKILL_DIR.resolve()
    return resolved if resolved != SKILL_DIR else None


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
