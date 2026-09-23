"""Terminal prompts, used only when a human is actually at the keyboard.

The CLI has two consumers. Claude gets exit 2 with a `NeedsChoice` payload and
answers by re-running with a flag. A person gets the same questions asked out
loud. Which one you are is decided by whether stdin is a terminal, so neither
consumer has to know about the other, and `--no-input` forces the machine
protocol if that detection is ever wrong.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from ..exceptions import PMError


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    detail: str = ""


def is_interactive() -> bool:
    """True when there is a human to answer."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def ask(question: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = _read(f"{question}{suffix}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        print("  Hace falta una respuesta.")


def ask_secret(question: str) -> str:
    """Read a token without echoing it, so it stays out of the scrollback."""
    while True:
        try:
            answer = getpass.getpass(f"{question}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise PMError("Cancelado.") from None
        if answer:
            return answer
        print("  Hace falta una respuesta.")


def confirm(question: str, *, default: bool = True) -> bool:
    suffix = "[S/n]" if default else "[s/N]"
    answer = _read(f"{question} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer[0] in "syt"


def choose(question: str, options: Sequence[Choice], *, multi: bool = False) -> list[str]:
    """Numbered menu. Returns the chosen ids, in the order they were offered."""
    if not options:
        raise PMError(f"{question} — no hay opciones para elegir.")
    if len(options) == 1 and not multi:
        print(f"\n{question}\n  → {options[0].label} (única opción)")
        return [options[0].id]

    print(f"\n{question}")
    width = len(str(len(options)))
    pad = max(len(o.label) for o in options)
    for index, option in enumerate(options, 1):
        detail = f"  {option.detail}" if option.detail else ""
        print(f"  {index:>{width}}) {option.label:<{pad}}{detail}")

    hint = "números separados por coma, o 'todos'" if multi else "número"
    while True:
        picked = _parse_selection(_read(f"> elegí ({hint}): "), len(options), multi=multi)
        if picked:
            return [options[i].id for i in picked]
        print("  No entendí. Probá de nuevo.")


def _parse_selection(raw: str, count: int, *, multi: bool) -> list[int]:
    """Indexes chosen from a 1-based menu, or empty when the answer makes no sense."""
    cleaned = raw.strip()
    if not cleaned:
        return []
    if multi and cleaned.lower() in {"todos", "todas", "all", "*"}:
        return list(range(count))

    parts = [p for p in cleaned.replace(",", " ").split() if p]
    if not multi and len(parts) != 1:
        return []

    indexes: list[int] = []
    for part in parts:
        if not part.isdigit():
            return []
        value = int(part) - 1
        if not 0 <= value < count or value in indexes:
            return []
        indexes.append(value)
    return indexes


def _read(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise PMError("Cancelado.") from None
