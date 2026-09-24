"""Composition roots for command handlers: provider and the guard."""

from __future__ import annotations

from typing import Any

from ..application.repo_context import RepoContext
from ..application.scope import ScopeGuard
from ..domain.ports import IssueProvider
from ..infrastructure.providers._registry import create_provider


def build_provider(config: RepoContext) -> IssueProvider:
    """Provider pinned to the workspace declared in `.pm.toml`."""
    profile = config.profile
    return create_provider(
        config.provider_type,
        token=config.require_token(),
        workspace_id=config.scope.workspace_id,
        auth_hint=(
            f"Credential profile {profile.name!r} was rejected for workspace "
            f"{config.scope.workspace_id} declared in {config.pm_file.path}. The token was rotated "
            f"or cannot reach that workspace: replace it with `pm creds add --name {profile.name} "
            f"--provider {profile.provider_type.value} --force`, or run `pm doctor`."
        ),
    )


def prepare_write(args: Any) -> tuple[RepoContext, IssueProvider, ScopeGuard]:
    """Everything a mutating command needs, including the scope check.

    Commands never touch the provider's mutating methods themselves — they go
    through the guard this returns.
    """
    config = RepoContext.load(profile_override=args.profile)
    provider = build_provider(config)
    guard = ScopeGuard(
        provider=provider,
        scope=config.scope,
        defaults=config.pm_file.defaults,
        dry_run=getattr(args, "dry_run", False),
        allow_structural_changes=getattr(args, "allow_structural_changes", False),
    )
    return config, provider, guard


def prepare_read(args: Any) -> tuple[RepoContext, IssueProvider]:
    """Reads skip the guard entirely — they pay no verification cost."""
    config = RepoContext.load(profile_override=args.profile)
    return config, build_provider(config)
