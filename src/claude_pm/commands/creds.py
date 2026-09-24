"""`creds add`, `creds list` — manage `~/.claude/pm/credentials.toml`."""

from __future__ import annotations

import os
import sys
from argparse import Namespace

from ..config import credentials_path
from ..enums import ProviderType
from ..exceptions import EXIT_OK
from ..repositories.credentials_repository import list_profiles
from ..services.credential_service import pick_workspace_id, probe_token, save_profile
from ..services.next_step import next_step
from ._input import NEW_TOKEN_ENV, can_prompt, credential_fields
from ._output import print_json, print_profile_saved


def list_all(args: Namespace) -> int:
    path = credentials_path()
    print_json(
        {
            "path": str(path),
            "exists": path.is_file(),
            "profiles": [p.redacted() for p in list_profiles(path)],
        }
    )
    return EXIT_OK


def add(args: Namespace) -> int:
    provider, token, name = credential_fields(
        ProviderType.parse(args.provider) if args.provider else None,
        args.token or os.environ.get(NEW_TOKEN_ENV),
        args.name,
        may_prompt=can_prompt(args),
    )
    email, reachable = probe_token(provider, token)
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

    save_profile(name, provider, token, workspace_id, force=args.force)
    print_profile_saved(name, email, reachable, workspace_id)
    print(next_step().render(), file=sys.stderr)

    return EXIT_OK
