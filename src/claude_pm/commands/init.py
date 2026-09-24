"""`init` — write this repo's `.pm.toml`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..application.onboarding import next_step
from ..application.profiles import authenticate_token, pick_workspace_id, save_profile
from ..application.scope_discovery import Option, Pick, choose_profile, discover_scope
from ..domain.binding import ProviderType
from ..exceptions import EXIT_OK, PMError
from ..infrastructure.config_files.credentials_store import list_profiles
from ..infrastructure.config_files.pm_file import render_pm_toml
from ..infrastructure.providers._registry import create_provider
from ..infrastructure.repo_detect import PM_FILE_NAME, find_repo_root
from ._input import can_prompt
from ._output import print_json
from ._profile_prompts import TOKEN_SOURCE_HINT, ask_provider, print_profile_saved
from ._prompt import Choice, ask, ask_secret, choose


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
    provider = ProviderType.parse(args.provider) if args.provider else ask_provider()
    token = ask_secret(f"{provider.value} token ({TOKEN_SOURCE_HINT[provider]})").strip()

    email, reachable = authenticate_token(provider, token)
    name = ask("Name for this profile", default=provider.value)
    workspace_id = pick_workspace_id(None, reachable)

    save_profile(name, provider, token, workspace_id)
    print_profile_saved(name, email, reachable, workspace_id)

    args.profile = name
    args.provider = provider.value
