"""Typed exceptions surfaced to the CLI layer.

Exit codes:
    0 — success
    1 — fatal error (PMError, ConfigError, ProviderError without exit override)
    2 — needs user choice (NeedsChoice; payload is JSON-printed to stdout)
    4 — refused: the write targets something outside this repo's declared scope
"""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_CHOICE = 2
EXIT_SCOPE = 4


class PMError(Exception):
    """Base — any recoverable error surfaced to the user."""

    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(PMError):
    """Configuration is missing or malformed (.pm.toml, credentials.toml, paths)."""


class ProviderError(PMError):
    """An issue-tracker adapter (Linear, ClickUp) failed."""


class ScopeViolation(PMError):
    """A mutation targeted something outside the repo's declared scope.

    Raised only by `application.scope`, which is the single place allowed to call
    the provider's mutating methods.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=EXIT_SCOPE)


class NeedsChoice(PMError):
    """Caller must pick from options. `payload` is JSON-printed to stdout."""

    def __init__(self, message: str, payload: dict[str, Any]) -> None:
        super().__init__(message, exit_code=EXIT_NEEDS_CHOICE)
        self.payload = payload
