"""`doctor` — degrades by stage, since a diagnostic that needs everything configured is useless."""

from __future__ import annotations

import argparse
import sys

from .. import __version__
from ..config import SKILL_FILE, credentials_path
from ..dependencies.provider import get_provider
from ..dependencies.repo_config import get_repo_config
from ..exceptions import EXIT_ERROR, EXIT_OK, PMError, ProviderError
from ..models.repo_config import RepoConfig
from ..repositories.credentials_repository import insecure_permissions_warning, list_profiles
from ..repositories.git_repo import find_pm_file
from ..services.next_step import next_step
from ..services.scope_discovery_service import verify_declared_scope


def run(args: argparse.Namespace) -> int:
    print(f"project-manager-skill {__version__} — doctor")
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
        config = get_repo_config(args)
    except PMError as exc:
        print(f"  Config:        FAILED — {exc}")
        return EXIT_ERROR

    _report_config(config)

    return _report_connectivity(config)


def _report_credentials() -> bool:
    """False when there is nothing usable yet."""
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
    if warning := insecure_permissions_warning(path):
        print(f"  WARNING:       {warning}")

    return True


def _report_config(config: RepoConfig) -> None:
    print(f"  Repo:          {config.repo_root}")
    print(f"  .pm.toml:      {config.pm_file.path}")
    print(f"  Provider:      {config.provider_type.value}")
    print(f"  Profile:       {config.profile.name}")
    print(f"  Scope:         {config.scope.describe()}")
    if config.pm_file.defaults.labels:
        print(f"  Auto-labels:   {', '.join(config.pm_file.defaults.labels)}")


def _report_connectivity(config: RepoConfig) -> int:
    print("  Provider ping: testing...")
    try:
        provider = get_provider(config)
        print(f"  Provider ping: ok — authenticated as {provider.viewer_email()}")
    except ProviderError as exc:
        print(f"  Provider ping: FAILED — {exc}")
        return EXIT_ERROR

    reachable = provider.reachable_workspace_ids()
    if config.scope.workspace_id not in reachable:
        print(
            f"  Pin workspace: FAILED — profile {config.profile.name!r} cannot reach workspace "
            f"{config.scope.workspace_id}. It reaches: {', '.join(reachable) or '(none)'}. "
            "Wrong profile for this repo, or the token was rotated."
        )
        return EXIT_ERROR

    print(f"  Pin workspace: ok — the token reaches {config.scope.workspace_id}")

    try:
        warnings = verify_declared_scope(provider, config.scope, config.pm_file.path)
    except PMError as exc:
        print(f"  Board:         FAILED — {exc}")
        return EXIT_ERROR

    print("  Board:         ok — the space and every list exist")
    for warning in warnings:
        print(f"  WARNING:       {warning}")
    print(next_step().render())

    return EXIT_OK
