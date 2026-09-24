"""`init` — write this repo's `.pm.toml`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..config import PM_FILE_NAME
from ..enums import ProviderType
from ..exceptions import EXIT_OK, PMError
from ..repositories.credentials_repository import list_profiles
from ..repositories.git_repo import find_repo_root
from ..repositories.pm_file_repository import render_pm_toml
from ..repositories.providers.factory import create_provider
from ..services.credential_service import pick_workspace_id, probe_token, save_profile
from ..services.next_step import next_step
from ..services.scope_discovery_service import Option, Pick, choose_profile, discover_scope
from ._input import Choice, can_prompt, choose, credential_fields
from ._output import print_json, print_profile_saved


def run(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    if repo_root is None:
        raise PMError(f"Not inside a git repository, so there is no root to put {PM_FILE_NAME} in.")

    pm_file_path = repo_root / PM_FILE_NAME
    if pm_file_path.exists() and not args.force and not args.dry_run:
        raise PMError(f"{pm_file_path} already exists. Re-run with --force to overwrite it.")

    interactive = can_prompt(args)
    if interactive and not list_profiles():
        _add_first_credential(args)

    pick: Pick = _ask if interactive else _refuse
    provider = ProviderType.parse(args.provider) if args.provider else None
    profile = choose_profile(list_profiles(), name=args.profile, provider=provider, pick=pick)
    scope = discover_scope(
        lambda workspace_id: create_provider(
            profile.provider_type, token=profile.token, workspace_id=workspace_id
        ),
        workspace_id=args.workspace_id or profile.workspace_id,
        team_id=args.space_id,
        project_ids=args.list_id,
        pick=pick,
    )
    pm_toml = render_pm_toml(
        provider_name=profile.provider_type.value, profile_name=profile.name, scope=scope
    )

    if args.dry_run:
        print(pm_toml)
        return EXIT_OK

    pm_file_path.write_text(pm_toml, encoding="utf-8")
    print_json(
        {
            "ok": True,
            "written": str(pm_file_path),
            "repo": repo_root.name,
            "profile": profile.name,
            "scope": scope.describe(),
            "commit": "Commit this file so the team shares the same binding.",
        }
    )
    print(next_step(repo_root).render(), file=sys.stderr)

    return EXIT_OK


def _ask(question: str, options: Sequence[Option], _flag: str, multi: bool) -> list[str]:
    return choose(
        question, [Choice(id=o.id, label=o.label, detail=o.id) for o in options], multi=multi
    )


def _refuse(question: str, options: Sequence[Option], flag: str, multi: bool) -> list[str]:
    listed = "\n".join(f"  {o.id}  {o.label}" for o in options)
    repeat = " (repeatable)" if multi else ""
    raise PMError(f"{question} Pass {flag} <ID>{repeat}. Options:\n{listed}")


def _add_first_credential(args: argparse.Namespace) -> None:
    """Ask for a token here rather than sending the user off to another command."""
    print("No credentials saved yet.")
    provider, token, name = credential_fields(
        ProviderType.parse(args.provider) if args.provider else None, None, None, may_prompt=True
    )
    email, reachable = probe_token(provider, token)
    workspace_id = pick_workspace_id(None, reachable)

    save_profile(name, provider, token, workspace_id)
    print_profile_saved(name, email, reachable, workspace_id)

    args.profile = name
    args.provider = provider.value
