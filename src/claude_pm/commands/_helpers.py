"""Shared helpers for command handlers — wiring + JSON serialization."""

from __future__ import annotations

import json
from typing import Any

from ..application.scope import DryRun, ScopeGuard, build_guard, verify_workspace_pin
from ..application.setup_flow import SetupService
from ..config import Config
from ..domain.models import Briefing, Issue
from ..domain.ports import ContextProvider, IssueProvider
from ..infrastructure.cache import JsonFileCacheRepository
from ..infrastructure.context.null import NullContext
from ..infrastructure.context.obsidian import ObsidianVaultContext
from ..infrastructure.providers._registry import get_provider


def build_provider(config: Config) -> IssueProvider:
    """Provider pinned to the workspace declared in `.pm.toml`."""
    return get_provider(
        config.provider_name,
        api_key=config.require_pak(),
        workspace_id=config.scope.workspace_id,
    )


def build_context(config: Config) -> ContextProvider:
    if config.vault_path is None:
        return NullContext()
    return ObsidianVaultContext(config.vault_path)


def get_cache_repo(config: Config) -> JsonFileCacheRepository:
    return JsonFileCacheRepository(config.cache_path, config.fingerprint)


def prepare_write(args: Any) -> tuple[Config, IssueProvider, ScopeGuard]:
    """Everything a mutating command needs, including the scope check.

    Commands never touch the provider's mutating methods themselves — they go
    through the guard this returns.
    """
    config = Config.load(args.repo_name, profile_override=getattr(args, "profile", None))
    provider = build_provider(config)
    verify_workspace_pin(config, provider)
    cache = SetupService(provider, get_cache_repo(config), config).ensure()
    guard = build_guard(
        config,
        provider,
        cache,
        dry_run=getattr(args, "dry_run", False),
        allow_structural=getattr(args, "allow_structural_changes", False),
        verify_pin=False,
    )
    return config, provider, guard


def prepare_read(args: Any) -> tuple[Config, IssueProvider]:
    """Reads skip the guard entirely — they pay no verification cost."""
    config = Config.load(args.repo_name, profile_override=getattr(args, "profile", None))
    return config, build_provider(config)


def issue_to_dict(issue: Issue) -> dict[str, Any]:
    return {
        "identifier": issue.identifier,
        "title": issue.title,
        "priority": issue.priority,
        "url": issue.url,
        "state": {"id": issue.state.id, "name": issue.state.name},
        "project": (
            {"id": issue.project.id, "name": issue.project.name} if issue.project else None
        ),
    }


def briefing_to_dict(briefing: Briefing) -> dict[str, Any]:
    return {
        "repo": briefing.repo,
        "project": briefing.project_name,
        "vault_available": briefing.vault_available,
        "vault_excerpt": briefing.vault_excerpt,
        "issues_by_state": {
            state: [issue_to_dict(i) for i in issues]
            for state, issues in briefing.issues_by_state.items()
        },
        "total_open": briefing.total_open,
    }


def print_result(outcome: Any, render: Any) -> None:
    """Print a dry-run preview, or the real result via `render`."""
    if isinstance(outcome, DryRun):
        print_json(outcome.to_dict())
    else:
        print_json(render(outcome))


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
