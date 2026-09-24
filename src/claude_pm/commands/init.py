"""`init` — write this repo's `.pm.toml`.

Discovery happens here so nobody has to hand-write ids. Every ambiguity is
reported as exit 2 with a choice payload, which the caller answers by re-running
with a flag.

That payload already carries the question and its options, so the interactive
wizard is not a second implementation: it is the same run, answering its own
exit 2 locally instead of returning it. Claude's path is untouched.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..application.onboarding import next_step
from ..application.profiles import (
    authenticate_token,
    infer_provider,
    load_profile,
    pick_workspace_id,
    save_profile,
)
from ..application.scope_discovery import discover_scope
from ..domain.binding import ProviderType
from ..domain.ports import IssueProvider
from ..exceptions import EXIT_OK, NeedsChoice, PMError
from ..infrastructure.config_files.credentials_store import list_profiles
from ..infrastructure.config_files.pm_file import render_pm_toml
from ..infrastructure.providers._registry import create_provider
from ..infrastructure.repo_detect import PM_FILE_NAME, find_repo_root
from ._input import can_prompt
from ._output import print_json
from ._profile_prompts import TOKEN_SOURCE_HINT, ask_provider, print_profile_saved
from ._prompt import Choice, ask, ask_secret, choose

# action → (arg to set, question, key holding the options, multi-select)
_QUESTIONS: dict[str, tuple[str, str, str, bool]] = {
    "choose-provider": ("provider", "Which tracker does this repo use?", "providers", False),
    "choose-profile": ("profile", "Which credential does this repo use?", "profiles", False),
    "choose-workspace": ("workspace_id", "Which workspace?", "workspaces", False),
    "choose-space": ("space_id", "Which space?", "spaces", False),
    "choose-list": ("list_id", "Which list(s) does this repo write to?", "lists", True),
}


def run(args: argparse.Namespace) -> int:
    if not can_prompt(args):
        return _write_pm_file(args)

    if not list_profiles():
        _add_first_credential(args)

    while True:
        try:
            return _write_pm_file(args)
        except NeedsChoice as needs_choice:
            _answer(args, needs_choice.payload)


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


def _answer(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    """Ask the question this exit-2 payload describes, and record the answer in `args`."""
    action = str(payload.get("action"))
    question_spec = _QUESTIONS.get(action)
    if question_spec is None:
        raise PMError(f"Don't know how to ask {action!r} interactively.")

    arg_attr, question, options_key, multi = question_spec
    picked = choose(question, _options(payload.get(options_key, [])), multi=multi)
    setattr(args, arg_attr, picked if multi else picked[0])


def _options(raw: list[Any]) -> list[Choice]:
    """Turn a payload's options into menu entries, whatever shape they arrived in."""
    choices: list[Choice] = []
    for option in raw:
        if isinstance(option, str):
            choices.append(Choice(id=option, label=option))
            continue
        identifier = str(option.get("id") or option.get("name"))
        label = str(option.get("name") or identifier)
        detail = str(option["id"]) if option.get("id") and option.get("name") else ""
        choices.append(
            Choice(id=identifier, label=label, detail=detail or str(option.get("provider", "")))
        )
    return choices


def _write_pm_file(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    if repo_root is None:
        raise PMError(f"Not inside a git repository, so there is no root to put {PM_FILE_NAME} in.")

    pm_file_path = repo_root / PM_FILE_NAME
    if pm_file_path.exists() and not args.force and not args.dry_run:
        raise PMError(f"{pm_file_path} already exists. Re-run with --force to overwrite it.")

    provider_type = infer_provider(args.provider, args.profile)
    profile = load_profile(args.profile, provider=provider_type)
    if profile.provider_type is not provider_type:
        raise PMError(
            f"Profile {profile.name!r} is for {profile.provider_type.value}, "
            f"but this repo wants {provider_type.value}."
        )

    def make_provider(workspace_id: str | None) -> IssueProvider:
        return create_provider(provider_type, token=profile.token, workspace_id=workspace_id)

    scope = discover_scope(
        make_provider,
        workspace_id=args.workspace_id or profile.workspace_id,
        team_id=args.space_id,
        project_ids=args.list_id or None,
    )

    pm_toml_text = render_pm_toml(
        provider_name=provider_type.value,
        profile_name=profile.name,
        scope=scope,
    )

    if args.dry_run:
        print(pm_toml_text)
        return EXIT_OK

    pm_file_path.write_text(pm_toml_text, encoding="utf-8")
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
