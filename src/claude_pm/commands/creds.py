"""`creds add` / `creds list` — manage `~/.claude/pm/credentials.toml`."""

from __future__ import annotations

import argparse
import os
import sys

from ..application.onboarding import next_step
from ..application.profiles import authenticate_token, pick_workspace_id, save_profile
from ..domain.binding import ProviderType
from ..exceptions import EXIT_OK, PMError
from ..infrastructure.config_files.credentials_store import credentials_path, list_profiles
from ._input import can_prompt
from ._output import print_json
from ._profile_prompts import TOKEN_SOURCE_HINT, ask_provider, print_profile_saved
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
    may_prompt = can_prompt(args)

    provider_type = ProviderType.parse(args.provider) if args.provider else None
    if provider_type is None:
        if not may_prompt:
            raise PMError("Missing --provider. Supported: linear, clickup.")
        provider_type = ask_provider()

    token = args.token or os.environ.get(_ENV_NEW_TOKEN)
    if not token:
        if not may_prompt:
            raise PMError(
                f"No token given. Pass --token, or set {_ENV_NEW_TOKEN} to keep it out of "
                f"your shell history."
            )
        token = ask_secret(f"{provider_type.value} token ({TOKEN_SOURCE_HINT[provider_type]})")

    name = args.name
    if not name:
        if not may_prompt:
            raise PMError("Missing --name for the profile.")
        name = ask("Name for this profile", default=provider_type.value)

    email, reachable = authenticate_token(provider_type, token.strip())
    workspace_id = pick_workspace_id(args.workspace_id, reachable)

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
    print_profile_saved(name, email, reachable, workspace_id)
    print(next_step().render(), file=sys.stderr)
    return EXIT_OK
