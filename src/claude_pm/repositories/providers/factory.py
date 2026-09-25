from __future__ import annotations

from typing import Protocol

from ...enums import ProviderType
from .base import IssueProvider
from .clickup import ClickUpProvider
from .linear import LinearProvider


class ProviderFactory(Protocol):
    """Protocols have no `__init__`, so `type[IssueProvider]` would leave the call unchecked."""

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
    return PROVIDERS[provider_type](token=token, workspace_id=workspace_id, auth_hint=auth_hint)
