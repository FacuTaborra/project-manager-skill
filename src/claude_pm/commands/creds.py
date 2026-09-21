"""`creds add` / `creds list` / `creds import` — manage `~/.claude/pm/credentials.toml`."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from ..application.onboarding import next_step
from ..credentials import credentials_path, list_profiles
from ..domain.models import Team
from ..enums import ProviderType
from ..exceptions import EXIT_OK, PMError, ProviderError
from ..infrastructure.providers._registry import get_provider
from ._helpers import print_json

LEGACY_SECRETS = {
    ProviderType.LINEAR: (Path.home() / ".claude" / "secrets" / "linear-pak.env", "LINEAR_API_KEY"),
    ProviderType.CLICKUP: (
        Path.home() / ".claude" / "secrets" / "clickup-pak.env",
        "CLICKUP_API_KEY",
    ),
}

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
    """Verify a token against the API, then store it as a named profile.

    Verifying first matters: a mistyped token fails here, next to the paste that
    caused it, instead of three commands later where the error no longer looks
    like its cause.
    """
    path = credentials_path()
    provider_type = _provider(args.provider)
    token = _token(args)

    if any(p.name == args.name for p in list_profiles(path)) and not args.force:
        raise PMError(
            f"Profile {args.name!r} already exists in {path}. Re-run with --force to replace it."
        )

    probe = get_provider(provider_type, api_key=token)
    try:
        email = probe.viewer_email()
        reachable = probe.list_workspaces()
    except ProviderError as exc:
        raise PMError(f"That token does not work: {exc}") from exc

    workspace_id = _workspace_id(args.workspace_id, reachable)

    if args.dry_run:
        print_json(
            {
                "dry_run": True,
                "would_add": args.name,
                "authenticated_as": email,
                "workspaces": [{"id": w.id, "name": w.name} for w in reachable],
            }
        )
        return EXIT_OK

    _write_profiles(path, [(args.name, provider_type, token, workspace_id)], replace=args.force)

    print(f"  ✓ token válido — autenticado como {email}")
    print(
        f"  ✓ alcanza {len(reachable)} workspace(s): "
        + ", ".join(f"{w.name} ({w.id})" for w in reachable)
    )
    if workspace_id:
        print(f"  ✓ perfil fijado a {workspace_id}")
    print(f"  ✓ perfil {args.name!r} escrito en {path}")
    print(next_step().render())
    return EXIT_OK


def run_import(args: argparse.Namespace) -> int:
    """Read the old `~/.claude/secrets/*.env` files once and write profiles from them."""
    path = credentials_path()
    existing = {p.name for p in list_profiles(path)}

    found = [
        (f"{provider.value}-default", provider, token, None)
        for provider, (secret_file, key) in LEGACY_SECRETS.items()
        if (token := _read_env_key(secret_file, key))
    ]
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

    _write_profiles(path, new)
    print_json({"ok": True, "path": str(path), "added": [name for name, *_ in new]})
    print(next_step().render())
    return EXIT_OK


# -- internals ---------------------------------------------------------------


def _provider(raw: str) -> ProviderType:
    try:
        return ProviderType(raw)
    except ValueError:
        supported = ", ".join(p.value for p in ProviderType)
        raise PMError(f"Unknown provider {raw!r}. Supported: {supported}.") from None


def _token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get(_ENV_NEW_TOKEN)
    if not token:
        raise PMError(
            f"No token given. Pass --token, or set {_ENV_NEW_TOKEN} to keep it out of "
            f"your shell history."
        )
    return token.strip()


def _workspace_id(declared: str | None, reachable: list[Team]) -> str | None:
    if declared:
        if not any(w.id == declared for w in reachable):
            seen = ", ".join(f"{w.name} ({w.id})" for w in reachable) or "(none)"
            raise PMError(f"That token cannot reach workspace {declared}. It reaches: {seen}.")
        return declared
    return reachable[0].id if len(reachable) == 1 else None


def _write_profiles(
    path: Path,
    entries: Sequence[tuple[str, ProviderType, str, str | None]],
    *,
    replace: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, stat.S_IRWXU)

    if replace and path.is_file():
        names = {name for name, *_ in entries}
        path.write_text(_without(path.read_text(encoding="utf-8"), names), encoding="utf-8")

    header = "" if path.is_file() and path.read_text(encoding="utf-8").strip() else "version = 1\n"
    blocks = []
    for name, provider, token, workspace_id in entries:
        block = (
            f'\n[profiles.{name}]\nprovider     = "{provider.value}"\ntoken        = "{token}"\n'
        )
        if workspace_id:
            block += f'workspace_id = "{workspace_id}"\n'
        blocks.append(block)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + "".join(blocks))

    if sys.platform != "win32":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _without(text: str, names: set[str]) -> str:
    """Drop the given [profiles.X] tables so --force can replace rather than duplicate."""
    kept: list[str] = []
    dropping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            dropping = any(stripped == f"[profiles.{name}]" for name in names)
        if not dropping:
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _read_env_key(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    prefix = f"{key}="
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip().removeprefix("export ")
            if not line or line.startswith("#") or not line.startswith(prefix):
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value and value != "REPLACE_ME":
                return value
    except OSError:
        return None
    return None
