"""Shared key-validation for the two TOML files this package reads.

Both `.pm.toml` and `credentials.toml` reject unknown keys instead of
ignoring them — the old INI format swallowed anything it did not recognise,
which is how `.pm.toml`'s `label:` key sat there doing nothing for months.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .exceptions import ConfigError


def reject_unknown(raw: dict[str, Any], allowed: set[str], path: Path, where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) in {where}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
