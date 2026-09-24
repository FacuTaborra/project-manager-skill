"""Shared helpers for the two TOML files this package reads and writes.

Both `.pm.toml` and `credentials.toml` reject unknown keys instead of
ignoring them — the old INI format swallowed anything it did not recognise,
which is how `.pm.toml`'s `label:` key sat there doing nothing for months.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..exceptions import ConfigError

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def toml_string(value: str) -> str:
    """Render `value` as a TOML basic string.

    The standard library reads TOML but cannot write it, so this is the one
    escaper both writers share. Control characters are escaped too: a token
    pasted with a stray newline should fail at the API, not corrupt the file
    that every later command has to parse.
    """
    return '"' + "".join(_escape(char) for char in value) + '"'


def _escape(char: str) -> str:
    if char in _ESCAPES:
        return _ESCAPES[char]
    if ord(char) < 0x20 or ord(char) == 0x7F:
        return f"\\u{ord(char):04x}"
    return char


def reject_unknown_keys(
    table: dict[str, Any], allowed_keys: set[str], path: Path, table_label: str
) -> None:
    unknown = sorted(set(table) - allowed_keys)
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) in {table_label}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed_keys))}."
        )
