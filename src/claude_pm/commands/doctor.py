"""`doctor` — report where this machine stands, and what to do next.

Degrades by stage instead of failing on the first missing piece. A diagnostic
that only works once everything is configured is useless exactly when it is
needed most.
"""

from __future__ import annotations

import argparse
import sys

from ..application.onboarding import SKILL_FILE, next_step
from ..application.repo_context import RepoContext
from ..application.scope import verify_workspace_pin
from ..exceptions import EXIT_ERROR, EXIT_OK, PMError, ProviderError, ScopeViolation
from ..infrastructure.cache import find_legacy_caches
from ..infrastructure.config_files.credentials_store import (
    credentials_path,
    list_profiles,
    warn_if_world_readable,
)
from ..infrastructure.context.obsidian import DEFAULT_VAULT
from ..infrastructure.repo_detect import find_pm_file
from ._helpers import build_provider


def run(args: argparse.Namespace) -> int:
    print("claude-pm-skill — doctor")
    print(f"  Python:        {sys.version.split()[0]}")
    print(f"  Skill:         {SKILL_FILE} {'(installed)' if SKILL_FILE.is_file() else '(missing)'}")

    if not _report_credentials():
        print(next_step().render())
        return EXIT_OK

    if find_pm_file() is None:
        print("  Repo:          no .pm.toml — not bound to any board")
        print(next_step().render())
        return EXIT_OK

    try:
        config = RepoContext.load(args.repo_name, profile_override=args.profile)
    except PMError as exc:
        print(f"  Config:        FAILED — {exc}")
        return EXIT_ERROR

    _report_config(config)
    return _report_connectivity(config)


def _report_credentials() -> bool:
    """Print the credentials line. False when there is nothing usable yet."""
    path = credentials_path()
    try:
        profiles = list_profiles(path)
    except PMError as exc:
        print(f"  Credentials:   UNREADABLE — {exc}")
        return False

    if not profiles:
        print(f"  Credentials:   none ({path})")
        return False

    names = ", ".join(f"{p.name} ({p.provider_type.value})" for p in profiles)
    print(f"  Credentials:   {names}")
    if warning := warn_if_world_readable(path):
        print(f"  WARNING:       {warning}")
    return True


def _report_config(config: RepoContext) -> None:
    print(f"  Repo:          {config.repo_name}  ({config.repo_root})")
    print(f"  .pm.toml:      {config.pm_file.path}")
    print(f"  Provider:      {config.provider_type.value}")
    print(f"  Profile:       {config.profile.name}")
    print(f"  Scope:         {config.scope.describe()}")
    if config.pm_file.defaults.labels:
        print(f"  Auto-labels:   {', '.join(config.pm_file.defaults.labels)}")

    if config.vault_path:
        print(f"  Vault:         {config.vault_path}")
    else:
        print(
            f"  Vault:         not found (CLAUDE_MEMORY_PATH unset and {DEFAULT_VAULT} "
            f"does not exist). Tracker-only mode."
        )
    print(
        f"  Cache:         {config.cache_path}"
        f" {'(exists)' if config.cache_path.is_file() else '(not yet)'}"
    )

    if legacy := find_legacy_caches(config.vault_path):
        print(f"  Old caches:    {len(legacy)} orphaned file(s), safe to delete:")
        for path in legacy[:5]:
            print(f"                   {path}")


def _report_connectivity(config: RepoContext) -> int:
    print("  Provider ping: testing...")
    try:
        provider = build_provider(config)
        print(f"  Provider ping: ok — authenticated as {provider.viewer_email()}")
    except ProviderError as exc:
        print(f"  Provider ping: FAILED — {exc}")
        return EXIT_ERROR

    try:
        verify_workspace_pin(config, provider)
    except ScopeViolation as exc:
        print(f"  Pin workspace: FAILED — {exc}")
        return EXIT_ERROR

    print(f"  Pin workspace: ok — the token reaches {config.scope.workspace_id}")
    print(next_step().render())
    return EXIT_OK
