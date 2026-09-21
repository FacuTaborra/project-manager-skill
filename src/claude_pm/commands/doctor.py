"""`doctor` — report where this machine stands, and what to do next.

Degrades by stage instead of failing on the first missing piece. A diagnostic
that only works once everything is configured is useless exactly when it is
needed most.
"""

from __future__ import annotations

import argparse
import sys

from ..application.onboarding import SKILL_FILE, next_step
from ..config import DEFAULT_VAULT, Config
from ..credentials import credentials_path, list_profiles, warn_if_world_readable
from ..exceptions import EXIT_ERROR, EXIT_OK, PMError, ProviderError
from ..infrastructure.cache import find_legacy_caches
from ..infrastructure.repo_detect import find_pm_file
from ._helpers import build_provider


def run(args: argparse.Namespace) -> int:
    print("claude-pm-skill — doctor")
    print(f"  Python:        {sys.version.split()[0]}")
    print(f"  Skill:         {SKILL_FILE} {'(instalada)' if SKILL_FILE.is_file() else '(falta)'}")

    if not _report_credentials():
        print(next_step().render())
        return EXIT_OK

    if find_pm_file() is None:
        print("  Repo:          sin .pm.toml — no está atado a ningún tablero")
        print(next_step().render())
        return EXIT_OK

    try:
        config = Config.load(args.repo_name, profile_override=args.profile)
    except PMError as exc:
        print(f"  Config:        FALLA — {exc}")
        return EXIT_ERROR

    _report_config(config)
    return _report_connectivity(config)


def _report_credentials() -> bool:
    """Print the credentials line. False when there is nothing usable yet."""
    path = credentials_path()
    try:
        profiles = list_profiles(path)
    except PMError as exc:
        print(f"  Credenciales:  ILEGIBLE — {exc}")
        return False

    if not profiles:
        print(f"  Credenciales:  ninguna ({path})")
        return False

    names = ", ".join(f"{p.name} ({p.provider.value})" for p in profiles)
    print(f"  Credenciales:  {names}")
    if warning := warn_if_world_readable(path):
        print(f"  AVISO:         {warning}")
    return True


def _report_config(config: Config) -> None:
    print(f"  Repo:          {config.repo_name}  ({config.repo_root})")
    print(f"  .pm.toml:      {config.pm_file.path}")
    print(f"  Provider:      {config.provider_name.value}")
    print(f"  Perfil:        {config.profile.name}")
    print(f"  Scope:         {config.scope.describe()}")
    if config.pm_file.defaults.labels:
        print(f"  Auto-labels:   {', '.join(config.pm_file.defaults.labels)}")

    if config.vault_path:
        print(f"  Vault:         {config.vault_path}")
    else:
        print(
            f"  Vault:         no encontrado (CLAUDE_MEMORY_PATH sin setear y {DEFAULT_VAULT} "
            f"no existe). Modo tracker-only."
        )
    print(
        f"  Cache:         {config.cache_path}"
        f" {'(existe)' if config.cache_path.is_file() else '(todavía no)'}"
    )

    if legacy := find_legacy_caches(config.vault_path):
        print(f"  Caches viejos: {len(legacy)} archivo(s) huérfanos, se pueden borrar:")
        for path in legacy[:5]:
            print(f"                   {path}")


def _report_connectivity(config: Config) -> int:
    print("  Provider ping: probando...")
    try:
        provider = build_provider(config)
        print(f"  Provider ping: ok — autenticado como {provider.viewer_email()}")
        reachable = provider.workspace_ids()
    except ProviderError as exc:
        print(f"  Provider ping: FALLA — {exc}")
        return EXIT_ERROR

    if config.scope.workspace_id not in reachable:
        print(
            f"  Pin workspace: FALLA — el token alcanza {', '.join(reachable) or '(ninguno)'}, "
            f"no {config.scope.workspace_id}. Las escrituras van a ser rechazadas."
        )
        return EXIT_ERROR

    print(f"  Pin workspace: ok — el token alcanza {config.scope.workspace_id}")
    print(next_step().render())
    return EXIT_OK
