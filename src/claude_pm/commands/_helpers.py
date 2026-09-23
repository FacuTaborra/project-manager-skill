"""Shared helpers for command handlers — wiring + JSON serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..application.scope import DryRun, ScopeGuard, build_guard, verify_workspace_pin
from ..application.setup_flow import SetupService
from ..config import Config
from ..domain.models import Briefing, Issue
from ..domain.ports import ContextProvider, IssueProvider
from ..exceptions import PMError
from ..infrastructure.cache import JsonFileCacheRepository
from ..infrastructure.context.null import NullContext
from ..infrastructure.context.obsidian import ObsidianVaultContext
from ..infrastructure.providers._registry import get_provider
from ._prompt import is_interactive


def build_provider(config: Config) -> IssueProvider:
    """Provider pinned to the workspace declared in `.pm.toml`."""
    return get_provider(
        config.provider_name,
        api_key=config.require_token(),
        workspace_id=config.scope.workspace_id,
    )


def build_context(config: Config) -> ContextProvider:
    if config.vault_path is None:
        return NullContext()
    return ObsidianVaultContext(config.vault_path)


def build_cache_repo(config: Config) -> JsonFileCacheRepository:
    return JsonFileCacheRepository(config.cache_path, config.fingerprint)


def build_setup(config: Config, provider: IssueProvider) -> SetupService:
    return SetupService(provider, build_cache_repo(config), config)


def interactive(args: Any) -> bool:
    """True when a human is at the keyboard and hasn't opted out with --no-input."""
    return not getattr(args, "no_input", False) and is_interactive()


def read_text_arg(path: str | None, what: str) -> str | None:
    """Read a UTF-8 file passed as a `--*-file` flag, or pass `None` through.

    `what` names the flag in the error, so "Content file not found: x" points
    back at whichever file argument the caller is reading.
    """
    if path is None:
        return None
    target = Path(path).expanduser()
    if not target.is_file():
        raise PMError(f"{what} file not found: {target}")
    return target.read_text(encoding="utf-8")


def prepare_write(args: Any) -> tuple[Config, IssueProvider, ScopeGuard]:
    """Everything a mutating command needs, including the scope check.

    Commands never touch the provider's mutating methods themselves — they go
    through the guard this returns.
    """
    config = Config.load(args.repo_name, profile_override=getattr(args, "profile", None))
    provider = build_provider(config)
    verify_workspace_pin(config, provider)
    cache = build_setup(config, provider).verify().cache
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


def issue_to_dict(issue: Issue, *, with_description: bool = False) -> dict[str, Any]:
    payload = {
        "identifier": issue.identifier,
        "title": issue.title,
        "priority": issue.priority,
        "url": issue.url,
        "state": {"id": issue.state.id, "name": issue.state.name},
        "project": (
            {"id": issue.project.id, "name": issue.project.name} if issue.project else None
        ),
    }
    if with_description:
        payload["description"] = issue.description
    return payload


def issues_by_state_to_dict(grouped: dict[str, list[Issue]]) -> dict[str, list[dict[str, Any]]]:
    return {state: [issue_to_dict(i) for i in issues] for state, issues in grouped.items()}


def briefing_to_dict(briefing: Briefing) -> dict[str, Any]:
    return {
        "repo": briefing.repo,
        "project": briefing.project_name,
        "vault_available": briefing.vault_available,
        "vault_excerpt": briefing.vault_excerpt,
        "issues_by_state": issues_by_state_to_dict(briefing.issues_by_state),
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
