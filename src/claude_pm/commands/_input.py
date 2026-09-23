"""Reading a `--*-file` flag, and knowing whether a human is at the keyboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..exceptions import PMError
from ._prompt import is_interactive


def can_prompt(args: Any) -> bool:
    """True when a human is at the keyboard and hasn't opted out with --no-input."""
    return not getattr(args, "no_input", False) and is_interactive()


def read_text_arg(path: str | None, what: str) -> str | None:
    """Read a UTF-8 file passed as a `--*-file` flag, or pass an absent flag through as `None`.

    `what` names the flag in the error, so "Content file not found: x" points
    back at whichever file argument the caller is reading.
    """
    if not path:
        return None
    target = Path(path).expanduser()
    if not target.is_file():
        raise PMError(f"{what} file not found: {target}")
    return target.read_text(encoding="utf-8")
