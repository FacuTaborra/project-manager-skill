"""Composition roots for command handlers: provider, cache, and the guard."""

from __future__ import annotations

from typing import Any

from ..application.cache_refresh import CacheRefreshService
from ..application.repo_context import RepoContext
from ..application.scope import ScopeGuard, build_guard, verify_workspace_pin
from ..domain.ports import IssueProvider
from ..infrastructure.cache import JsonFileCacheRepository
from ..infrastructure.providers._registry import create_provider


def build_provider(config: RepoContext) -> IssueProvider:
    """Provider pinned to the workspace declared in `.pm.toml`."""
    return create_provider(
        config.provider_type,
        token=config.require_token(),
        workspace_id=config.scope.workspace_id,
    )


def build_cache_repo(config: RepoContext) -> JsonFileCacheRepository:
    return JsonFileCacheRepository(config.cache_path, config.fingerprint)


def build_cache_refresher(config: RepoContext, provider: IssueProvider) -> CacheRefreshService:
    return CacheRefreshService(provider, build_cache_repo(config), config)


def prepare_write(args: Any) -> tuple[RepoContext, IssueProvider, ScopeGuard]:
    """Everything a mutating command needs, including the scope check.

    Commands never touch the provider's mutating methods themselves — they go
    through the guard this returns.
    """
    config = RepoContext.load(profile_override=args.profile)
    provider = build_provider(config)
    verify_workspace_pin(config, provider)
    cache = build_cache_refresher(config, provider).refresh().cache
    guard = build_guard(
        config,
        provider,
        cache,
        dry_run=getattr(args, "dry_run", False),
        allow_structural_changes=getattr(args, "allow_structural_changes", False),
        check_workspace_pin=False,
    )
    return config, provider, guard


def prepare_read(args: Any) -> tuple[RepoContext, IssueProvider]:
    """Reads skip the guard entirely — they pay no verification cost."""
    config = RepoContext.load(profile_override=args.profile)
    return config, build_provider(config)
