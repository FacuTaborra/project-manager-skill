from __future__ import annotations

from pathlib import Path
from typing import Any

from ..exceptions import ConfigError

_FIRST_PRINTABLE = 0x20
_DELETE = 0x7F
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
    """Control characters are escaped too: a token pasted with a stray newline should fail at the
    API, not corrupt a file every later command has to parse.
    """
    return '"' + "".join(_escape(char) for char in value) + '"'


def _escape(char: str) -> str:
    if char in _ESCAPES:
        return _ESCAPES[char]
    if ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE:
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
