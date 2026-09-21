#!/usr/bin/env python3
"""Deprecated entry point. Delegates to the `claude_pm` package in src/.

Kept for one release so existing `~/.claude/skills/pm` symlinks keep working and
their owners get a migration message instead of a traceback. The supported entry
point is the `pm` console script:

    uv tool install git+https://github.com/FacuTaborra/claude-pm-skill
"""
import os
import sys

if sys.version_info < (3, 11):
    sys.exit(
        f"pm requires Python >= 3.11 (found {sys.version_info.major}.{sys.version_info.minor}).\n"
        "Install it as a tool instead, which brings its own interpreter:\n"
        "  uv tool install git+https://github.com/FacuTaborra/claude-pm-skill"
    )

print("pm.py is deprecated — use the `pm` command instead.", file=sys.stderr)

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))

from claude_pm.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
