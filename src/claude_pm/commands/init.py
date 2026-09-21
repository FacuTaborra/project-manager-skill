"""`init` — write this repo's `.pm.toml`.

Discovery happens here so nobody has to hand-write ids. Ambiguity is reported as
exit 2 with a choice payload rather than an interactive prompt: the usual caller
is Claude, which cannot answer `input()`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..application.init_flow import build_scope, defaults_from_legacy, read_legacy_section
from ..application.onboarding import next_step
from ..application.toml_render import render_pm_toml
from ..credentials import load_profile
from ..domain.ports import IssueProvider
from ..enums import ProviderType
from ..exceptions import EXIT_OK, PMError
from ..infrastructure.providers._registry import get_provider
from ..infrastructure.repo_detect import PM_FILE_NAME, detect_repo_name, find_repo_root
from ._helpers import print_json

DEFAULT_LEGACY_PATH = Path.home() / ".claude" / "skills" / "pm" / "projects.pm"


def run(args: argparse.Namespace) -> int:
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
    raw = args.provider or (legacy.provider if legacy else None)
    if raw is None:
        raise PMError("Cannot tell which provider this repo uses. Pass --provider linear|clickup.")
    try:
        return ProviderType(raw)
    except ValueError:
        supported = ", ".join(p.value for p in ProviderType)
        raise PMError(f"Unknown provider {raw!r}. Supported: {supported}.") from None
