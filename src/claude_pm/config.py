"""Where pm reads and writes on disk."""

from __future__ import annotations

import os
from pathlib import Path

REPO_URL = "https://github.com/FacuTaborra/project-manager-skill"

PM_FILE_NAME = ".pm.toml"

DEFAULT_CREDENTIALS_PATH = Path.home() / ".claude" / "pm" / "credentials.toml"

SKILL_DIR = Path.home() / ".claude" / "skills" / "pm"
SKILL_FILE = SKILL_DIR / "SKILL.md"


def credentials_path() -> Path:
    env = os.environ.get("PM_CREDENTIALS_FILE")
    return Path(env).expanduser() if env else DEFAULT_CREDENTIALS_PATH


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"
