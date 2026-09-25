"""Exit codes:
0 — success
1 — error (PMError and its subclasses)
2 — needs a choice (NeedsChoice; the options are JSON-printed to stdout)
4 — refused: the write targets something outside this repo's declared scope
130 — interrupted
"""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_CHOICE = 2
EXIT_SCOPE = 4
EXIT_INTERRUPTED = 130


class PMError(Exception):
    exit_code = EXIT_ERROR


class ConfigError(PMError):
    """Configuration is missing or malformed (.pm.toml, credentials.toml, paths)."""


class ProviderError(PMError):
    """An issue-tracker adapter (Linear, ClickUp) failed."""


class ScopeViolation(PMError):
    """Raised only by the scope guard, the single place allowed to call the provider's writes."""

    exit_code = EXIT_SCOPE


class NeedsChoice(PMError):
    exit_code = EXIT_NEEDS_CHOICE

    def __init__(self, message: str, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.payload = payload
