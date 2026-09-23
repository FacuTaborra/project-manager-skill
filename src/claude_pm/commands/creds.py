"""`creds add` / `creds list` / `creds import` — manage `~/.claude/pm/credentials.toml`."""

from __future__ import annotations

import argparse
import os
import sys

from ..application.onboarding import next_step
from ..application.profiles import pick_workspace, verify_token
from ..credentials import (
    LEGACY_SECRETS,
    credentials_path,
    find_legacy_tokens,
    list_profiles,
    save_profile,
    write_profiles,
)
from ..enums import ProviderType
from ..exceptions import EXIT_OK, PMError
from ._helpers import interactive, print_json
from ._profile_io import WHERE_TO_GET_ONE, ask_provider, report
from ._prompt import ask, ask_secret

_ENV_NEW_TOKEN = "PM_NEW_TOKEN"


def run_list(args: argparse.Namespace) -> int:
    path = credentials_path()
    print_json(
        {
            "path": str(path),
            "exists": path.is_file(),
            "profiles": [p.redacted() for p in list_profiles(path)],
        }
    )
    return EXIT_OK


def run_add(args: argparse.Namespace) -> int:
    can_prompt = interactive(args)

    provider_type = ProviderType.parse(args.provider) if args.provider else None
    if provider_type is None:
        if not can_prompt:
            raise PMError("Missing --provider. Supported: linear, clickup.")
        provider_type = ask_provider()

    token = args.token or os.environ.get(_ENV_NEW_TOKEN)
    if not token:
        if not can_prompt:
            raise PMError(
                f"No token given. Pass --token, or set {_ENV_NEW_TOKEN} to keep it out of "
                f"your shell history."
            )
        token = ask_secret(f"Token de {provider_type.value} ({WHERE_TO_GET_ONE[provider_type]})")

    name = args.name
    if not name:
        if not can_prompt:
            raise PMError("Missing --name for the profile.")
        name = ask("Nombre para este perfil", default=provider_type.value)

    email, reachable = verify_token(provider_type, token.strip())
    workspace_id = pick_workspace(args.workspace_id, reachable)

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "would_add": name,
                "authenticated_as": email,
                "workspaces": [{"id": w.id, "name": w.name} for w in reachable],
            }
        )
        return EXIT_OK

    save_profile(name, provider_type, token.strip(), workspace_id, force=args.force)
    report(name, email, reachable, workspace_id)
    print(next_step().render(), file=sys.stderr)
    return EXIT_OK


def run_import(args: argparse.Namespace) -> int:
    """Read the old `~/.claude/secrets/*.env` files once and write profiles from them."""
    path = credentials_path()
    existing = {p.name for p in list_profiles(path)}

    found = find_legacy_tokens()
    if not found:
        locations = ", ".join(str(f) for f, _ in LEGACY_SECRETS.values())
        raise PMError(
            f"No legacy tokens found. Looked in: {locations}.\n"
            f"Use `pm creds add` instead if this is a fresh setup."
        )

    new = [entry for entry in found if entry[0] not in existing]
    if not new:
        print_json({"ok": True, "added": [], "note": "All legacy tokens are already imported."})
        return EXIT_OK

    if args.dry_run:
        print_json({"dry_run": True, "would_add": [name for name, *_ in new]})
        return EXIT_OK

    write_profiles(path, new)
    print_json({"ok": True, "path": str(path), "added": [name for name, *_ in new]})
    print(next_step().render(), file=sys.stderr)
    return EXIT_OK
