"""Prompts when a person is at the keyboard; without one (Claude, CI, `--no-input`) commands fail
naming the flag to pass instead."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..enums import ProviderType
from ..exceptions import PMError

NEW_TOKEN_ENV = "PM_NEW_TOKEN"

TOKEN_SOURCE_HINT = {
    ProviderType.CLICKUP: "ClickUp → Settings → Apps → API Token",
    ProviderType.LINEAR: "https://linear.app/settings/api (Read + Write)",
}


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    detail: str = ""


def is_interactive() -> bool:
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
        print("  An answer is required.")


def ask_secret(question: str) -> str:
    """Read a token without echoing it, so it stays out of the scrollback."""
    while True:
        try:
            answer = getpass.getpass(f"{question}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise PMError("Cancelled.") from None
        if answer:
            return answer
        print("  An answer is required.")


def choose(question: str, options: Sequence[Choice], *, multi: bool = False) -> list[str]:
    if not options:
        raise PMError(f"{question} — no options to choose from.")
    if len(options) == 1 and not multi:
        print(f"\n{question}\n  → {options[0].label} (only option)")
        return [options[0].id]

    print(f"\n{question}")
    width = len(str(len(options)))
    pad = max(len(o.label) for o in options)
    for index, option in enumerate(options, 1):
        detail = f"  {option.detail}" if option.detail else ""
        print(f"  {index:>{width}}) {option.label:<{pad}}{detail}")

    hint = "comma-separated numbers, or 'all'" if multi else "number"
    while True:
        picked = _parse_selection(_read(f"> choose ({hint}): "), len(options), multi=multi)
        if picked:
            return [options[i].id for i in picked]
        print("  Didn't understand that. Try again.")


def _parse_selection(raw: str, count: int, *, multi: bool) -> list[int]:
    """Empty when the answer makes no sense, so the caller asks again."""
    cleaned = raw.strip()
    if not cleaned:
        return []
    if multi and cleaned.lower() in {"all", "*"}:
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
        raise PMError("Cancelled.") from None


def can_prompt(args: Any) -> bool:
    return not getattr(args, "no_input", False) and is_interactive()


def read_text_arg(path: str | None, what: str) -> str | None:
    if not path:
        return None

    target = Path(path).expanduser()
    if not target.is_file():
        raise PMError(f"{what} file not found: {target}")

    return target.read_text(encoding="utf-8")


def ask_provider() -> ProviderType:
    [picked] = choose(
        "Which tracker does this repo use?",
        [Choice(id=p.value, label=p.value, detail=TOKEN_SOURCE_HINT[p]) for p in ProviderType],
    )
    return ProviderType(picked)


def credential_fields(
    provider: ProviderType | None, token: str | None, name: str | None, *, may_prompt: bool
) -> tuple[ProviderType, str, str]:
    if provider is None:
        if not may_prompt:
            raise PMError("Pass --provider linear or --provider clickup.")
        provider = ask_provider()

    if not token:
        if not may_prompt:
            raise PMError(
                f"No token given. Pass --token, or set {NEW_TOKEN_ENV} to keep it out of your "
                "shell history."
            )
        token = ask_secret(f"{provider.value} token ({TOKEN_SOURCE_HINT[provider]})")

    if not name:
        if not may_prompt:
            raise PMError("Pass --name to name the profile.")
        name = ask("Name for this profile", default=provider.value)

    return provider, token.strip(), name
