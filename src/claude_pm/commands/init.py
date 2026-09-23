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
from pathlib import Path
from typing import Any

from ..application.init_flow import (
    LegacySection,
    build_scope,
    defaults_from_legacy,
    read_legacy_section,
)
from ..application.onboarding import next_step
from ..application.profiles import (
    infer_provider,
    load_profile,
    pick_workspace,
    save_profile,
    verify_token,
)
from ..domain.binding import ProviderType
from ..domain.ports import IssueProvider
from ..exceptions import EXIT_OK, NeedsChoice, PMError
from ..infrastructure.config_files.credentials_store import list_profiles
from ..infrastructure.config_files.pm_file import render_pm_toml
from ..infrastructure.providers._registry import get_provider
from ..infrastructure.repo_detect import PM_FILE_NAME, detect_repo_name, find_repo_root
from ._helpers import interactive, print_json
from ._profile_io import WHERE_TO_GET_ONE, ask_provider, report
from ._prompt import Choice, ask, ask_secret, choose

DEFAULT_LEGACY_PATH = Path.home() / ".claude" / "skills" / "pm" / "projects.pm"

# action → (arg to set, question, key holding the options, multi-select)
_QUESTIONS: dict[str, tuple[str, str, str, bool]] = {
    "choose-provider": ("provider", "Which tracker does this repo use?", "providers", False),
    "choose-profile": ("profile", "Which credential does this repo use?", "profiles", False),
    "choose-workspace": ("workspace_id", "Which workspace?", "workspaces", False),
    "choose-space": ("space_id", "Which space?", "spaces", False),
    "choose-list": ("list_id", "Which list(s) does this repo write to?", "lists", True),
}


def run(args: argparse.Namespace) -> int:
    if not interactive(args):
        return _run_once(args)

    if not list_profiles():
        _add_first_credential(args)

    while True:
        try:
            return _run_once(args)
        except NeedsChoice as choice:
            _answer(args, choice.payload)


def _add_first_credential(args: argparse.Namespace) -> None:
    """Ask for a token here rather than sending the user off to another command."""
    print("No credentials saved yet.")
    provider = ProviderType.parse(args.provider) if args.provider else ask_provider()
    token = ask_secret(f"{provider.value} token ({WHERE_TO_GET_ONE[provider]})").strip()

    email, reachable = verify_token(provider, token)
    name = ask("Name for this profile", default=provider.value)
    workspace_id = pick_workspace(None, reachable)

    save_profile(name, provider, token, workspace_id)
    report(name, email, reachable, workspace_id)

    args.profile = name
    args.provider = provider.value


def _answer(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    """Ask the question this exit-2 payload describes, and record the answer in `args`."""
    action = str(payload.get("action"))
    plan = _QUESTIONS.get(action)
    if plan is None:
        raise PMError(f"Don't know how to ask {action!r} interactively.")

    key, question, options_key, multi = plan
    picked = choose(question, _options(payload.get(options_key, [])), multi=multi)
    setattr(args, key, picked if multi else picked[0])


def _options(raw: list[Any]) -> list[Choice]:
    """Turn a payload's options into menu entries, whatever shape they arrived in."""
    out: list[Choice] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Choice(id=item, label=item))
            continue
        identifier = str(item.get("id") or item.get("name"))
        label = str(item.get("name") or identifier)
        detail = str(item["id"]) if item.get("id") and item.get("name") else ""
        out.append(
            Choice(id=identifier, label=label, detail=detail or str(item.get("provider", "")))
        )
    return out


def _run_once(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    if repo_root is None:
        raise PMError(f"Not inside a git repository, so there is no root to put {PM_FILE_NAME} in.")

    target = repo_root / PM_FILE_NAME
    if target.exists() and not args.force and not args.dry_run:
        raise PMError(f"{target} already exists. Re-run with --force to overwrite it.")

    repo_name = args.repo_name or detect_repo_name(repo_root)
    legacy = _legacy(args, repo_name)

    provider_name = infer_provider(args.provider, args.profile, legacy.provider if legacy else None)
    profile = load_profile(args.profile, provider=provider_name)
    if profile.provider is not provider_name:
        raise PMError(
            f"Profile {profile.name!r} is for {profile.provider.value}, "
            f"but this repo wants {provider_name.value}."
        )

    def make_provider(workspace_id: str | None) -> IssueProvider:
        return get_provider(provider_name, api_key=profile.token, workspace_id=workspace_id)

    scope = build_scope(
        make_provider,
        workspace_id=args.workspace_id or profile.workspace_id,
        space_id=args.space_id,
        space_name=None if args.space_id else (legacy.space if legacy else None),
        list_ids=args.list_id or None,
        list_names=None if args.list_id else (list(legacy.projects) if legacy else None),
    )

    rendered = render_pm_toml(
        provider=provider_name.value,
        profile=profile.name,
        scope=scope,
        defaults=defaults_from_legacy(legacy),
    )

    if args.dry_run:
        print(rendered)
        return EXIT_OK

    target.write_text(rendered, encoding="utf-8")
    print_json(
        {
            "ok": True,
            "written": str(target),
            "repo": repo_name,
            "profile": profile.name,
            "scope": scope.describe(),
            "from_legacy": legacy is not None,
            "commit": "Commit this file so the team shares the same binding.",
        }
    )
    print(next_step(repo_root).render(), file=sys.stderr)
    return EXIT_OK


def _legacy(args: argparse.Namespace, repo_name: str) -> LegacySection | None:
    if not args.from_legacy:
        return None
    path = (
        Path(args.from_legacy).expanduser() if args.from_legacy is not True else DEFAULT_LEGACY_PATH
    )
    section = read_legacy_section(path, repo_name)
    if section is None:
        raise PMError(f"No [{repo_name}] section in {path}.")
    return section
