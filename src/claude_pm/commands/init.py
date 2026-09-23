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
from pathlib import Path
from typing import Any

from ..application.init_flow import build_scope, defaults_from_legacy, read_legacy_section
from ..application.onboarding import next_step
from ..application.prompt import Choice, ask, ask_secret, choose, is_interactive
from ..application.toml_render import render_pm_toml
from ..credentials import list_profiles, load_profile
from ..domain.ports import IssueProvider
from ..enums import ProviderType
from ..exceptions import EXIT_OK, NeedsChoice, PMError
from ..infrastructure.providers._registry import get_provider
from ..infrastructure.repo_detect import PM_FILE_NAME, detect_repo_name, find_repo_root
from . import creds
from ._helpers import print_json

DEFAULT_LEGACY_PATH = Path.home() / ".claude" / "skills" / "pm" / "projects.pm"

# action → (arg to set, question, key holding the options, multi-select)
_QUESTIONS: dict[str, tuple[str, str, str, bool]] = {
    "choose-provider": ("provider", "¿Qué tracker usa este repo?", "providers", False),
    "choose-profile": ("profile", "¿Qué credencial usa este repo?", "profiles", False),
    "choose-workspace": ("workspace_id", "¿Qué workspace?", "workspaces", False),
    "choose-space": ("space_id", "¿Qué space?", "spaces", False),
    "choose-list": ("list_id", "¿A qué lista(s) escribe este repo?", "lists", True),
}


def run(args: argparse.Namespace) -> int:
    if not _interactive(args):
        return _run_once(args)

    if not list_profiles():
        _add_first_credential(args)

    while True:
        try:
            return _run_once(args)
        except NeedsChoice as choice:
            _answer(args, choice.payload)


def _interactive(args: argparse.Namespace) -> bool:
    return not getattr(args, "no_input", False) and is_interactive()


def _add_first_credential(args: argparse.Namespace) -> None:
    """Ask for a token here rather than sending the user off to another command."""
    print("Todavía no hay credenciales guardadas.")
    provider = creds._provider(args.provider) if args.provider else creds.ask_provider()
    token = ask_secret(f"Token de {provider.value} ({creds.WHERE_TO_GET_ONE[provider]})").strip()

    email, reachable = creds.verify_token(provider, token)
    name = ask("Nombre para este perfil", default=provider.value)
    workspace_id = creds.pick_workspace(None, reachable)

    creds.save_profile(name, provider, token, workspace_id)
    creds.report(name, email, reachable, workspace_id)

    args.profile = name
    args.provider = provider.value


def _answer(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    """Ask the question this exit-2 payload describes, and record the answer in `args`."""
    action = str(payload.get("action"))
    plan = _QUESTIONS.get(action)
    if plan is None:
        raise PMError(f"No sé cómo preguntar {action!r} de forma interactiva.")

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

    provider_name = _provider_name(args, legacy)
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
            "commit": "Commiteá este archivo para que el equipo comparta el mismo binding.",
        }
    )
    print(next_step(repo_root).render())
    return EXIT_OK


def _legacy(args: argparse.Namespace, repo_name: str):  # type: ignore[no-untyped-def]
    if not args.from_legacy:
        return None
    path = (
        Path(args.from_legacy).expanduser() if args.from_legacy is not True else DEFAULT_LEGACY_PATH
    )
    section = read_legacy_section(path, repo_name)
    if section is None:
        raise PMError(f"No [{repo_name}] section in {path}.")
    return section


def _provider_name(args: argparse.Namespace, legacy) -> ProviderType:  # type: ignore[no-untyped-def]
    """Work out the provider without making the user state the obvious.

    A credential profile already carries one, so naming a profile — or having
    only profiles of one kind — settles it. Only a genuine ambiguity is worth
    asking about, and then it is exit 2 like every other choice, not a dead end.
    """
    raw = args.provider or (legacy.provider if legacy else None)
    if raw is not None:
        try:
            return ProviderType(raw)
        except ValueError:
            supported = ", ".join(p.value for p in ProviderType)
            raise PMError(f"Unknown provider {raw!r}. Supported: {supported}.") from None

    profiles = list_profiles()
    if args.profile:
        named = next((p for p in profiles if p.name == args.profile), None)
        if named is None:
            available = ", ".join(p.name for p in profiles) or "(none)"
            raise PMError(f"Profile {args.profile!r} not found. Available: {available}.")
        return named.provider

    providers = {p.provider for p in profiles}
    if len(providers) == 1:
        return providers.pop()
    if not providers:
        raise PMError(
            "No credential profiles yet, so there is no provider to infer.\n"
            "Run `pm creds add --name <nombre> --provider clickup --token pk_xxx` first."
        )

    raise NeedsChoice(
        "This repo could use either tracker. Re-run with --provider <name>, "
        "or with --profile <name> to let the credential decide.",
        {
            "action": "choose-provider",
            "providers": sorted(p.value for p in providers),
            "profiles": [p.redacted() for p in profiles],
        },
    )
