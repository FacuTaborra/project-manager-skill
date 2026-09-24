"""Provider registry — maps provider name → factory.

To add a new provider (GitHub, Jira, Notion, ...):
    1. Implement the IssueProvider Protocol in pm/infrastructure/providers/<name>.py
    2. Register it here: PROVIDERS[ProviderType.<NAME>] = <ClassName>
    3. Document setup in README

See CONTRIBUTING.md for details.
"""

from __future__ import annotations

from typing import Protocol

from ...enums import ProviderType
from ...exceptions import ConfigError
from .base import IssueProvider
from .clickup import ClickUpProvider
from .linear import LinearProvider


class ProviderFactory(Protocol):
    """The constructor shape every adapter must accept.

    `IssueProvider` is a Protocol and carries no constructor, so `type[IssueProvider]`
    would leave the call below unchecked. Adapter classes satisfy this structurally.
    """

    def __call__(
        self, token: str, *, workspace_id: str | None = None, auth_hint: str = ""
    ) -> IssueProvider: ...


PROVIDERS: dict[ProviderType, ProviderFactory] = {
    ProviderType.LINEAR: LinearProvider,
    ProviderType.CLICKUP: ClickUpProvider,
}


def create_provider(
    provider_type: ProviderType,
    *,
    token: str,
    workspace_id: str | None = None,
    auth_hint: str = "",
) -> IssueProvider:
    """Instantiate a provider by type, pinned to a token and (optionally) a workspace."""
    if provider_type not in PROVIDERS:
        available = ", ".join(p.value for p in PROVIDERS) or "(none)"
        raise ConfigError(
            f"Unknown provider '{provider_type}'. Available: {available}. "
            f"See CONTRIBUTING.md to add a new provider."
        )
    return PROVIDERS[provider_type](token=token, workspace_id=workspace_id, auth_hint=auth_hint)
