"""Provider registry — maps provider name → factory.

To add a new provider (GitHub, Jira, Notion, ...):
    1. Implement the IssueProvider Protocol in pm/infrastructure/providers/<name>.py
    2. Register it here: PROVIDERS[ProviderType.<NAME>] = <ClassName>
    3. Document setup in README

See CONTRIBUTING.md for details.
"""

from __future__ import annotations

from typing import Any

from ...domain.binding import ProviderType
from ...domain.ports import IssueProvider
from ...exceptions import ConfigError
from .clickup import ClickUpProvider
from .linear import LinearProvider

PROVIDERS: dict[ProviderType, type[IssueProvider]] = {
    ProviderType.LINEAR: LinearProvider,
    ProviderType.CLICKUP: ClickUpProvider,
}


def get_provider(name: ProviderType, **kwargs: Any) -> IssueProvider:
    """Instantiate a provider by name. kwargs are forwarded to its constructor."""
    if name not in PROVIDERS:
        available = ", ".join(p.value for p in PROVIDERS) or "(none)"
        raise ConfigError(
            f"Unknown provider '{name}'. Available: {available}. "
            f"See CONTRIBUTING.md to add a new provider."
        )
    return PROVIDERS[name](**kwargs)
