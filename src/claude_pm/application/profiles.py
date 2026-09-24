"""Credential profiles: prove a token works, save it, load it by name.

The ambient `LINEAR_API_KEY` / `CLICKUP_API_KEY` are never read: a token must not
depend on the directory you run from. CI passes `PM_TOKEN` explicitly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..domain.binding import CredentialProfile, ProviderType
from ..domain.models import Workspace
from ..exceptions import ConfigError, PMError, ProviderError
from ..infrastructure.config_files.credentials_store import (
    credentials_path,
    list_profiles,
    write_profiles,
)
from ..infrastructure.providers._registry import create_provider

_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ENV_TOKEN = "PM_TOKEN"

_SETUP_HINT = "Add one with `pm creds add --name <name> --provider <clickup|linear> --token ...`."


def authenticate_token(provider: ProviderType, token: str) -> tuple[str, list[Workspace]]:
    """Prove the token works before it is written anywhere.

    A mistyped token fails here, next to the paste that caused it, instead of
    three commands later where the error no longer looks like its cause.
    """
    probe = create_provider(provider, token=token)
    try:
        return probe.viewer_email(), probe.list_workspaces()
    except ProviderError as exc:
        raise PMError(f"That token does not work: {exc}") from exc


def pick_workspace_id(declared: str | None, reachable: list[Workspace]) -> str | None:
    """Pin the profile only when there is no doubt; `pm init` asks otherwise."""
    if declared:
        if not any(w.id == declared for w in reachable):
            seen = ", ".join(f"{w.name} ({w.id})" for w in reachable) or "(none)"
            raise PMError(f"That token cannot reach workspace {declared}. It reaches: {seen}.")
        return declared
    return reachable[0].id if len(reachable) == 1 else None


def load_profile(
    name: str, *, provider: ProviderType, path: Path | None = None
) -> CredentialProfile:
    """`PM_TOKEN` short-circuits the file entirely, for CI."""
    if env_token := os.environ.get(_ENV_TOKEN):
        return CredentialProfile(
            name=name,
            provider_type=provider,
            token=env_token,
            workspace_id=os.environ.get("PM_WORKSPACE_ID"),
        )

    profiles = list_profiles(path)
    if not profiles:
        raise ConfigError(f"No credential profiles in {path or credentials_path()}. {_SETUP_HINT}")

    match = next((p for p in profiles if p.name == name), None)
    if match is None:
        raise ConfigError(
            f"Credential profile {name!r} not found in {path or credentials_path()}. "
            f"Available: {', '.join(p.name for p in profiles)}."
        )

    return match


def save_profile(
    name: str,
    provider: ProviderType,
    token: str,
    workspace_id: str | None,
    *,
    force: bool = False,
    path: Path | None = None,
) -> None:
    if not _PROFILE_NAME_RE.match(name):
        raise PMError(
            f"Profile name {name!r} is not a valid TOML key. Use only letters, digits, '_' and '-'."
        )
    target = path or credentials_path()
    if any(p.name == name for p in list_profiles(target)) and not force:
        raise PMError(
            f"Profile {name!r} already exists in {target}. Re-run with --force to replace it."
        )
    write_profiles(
        target,
        [
            CredentialProfile(
                name=name, provider_type=provider, token=token, workspace_id=workspace_id
            )
        ],
        replace=force,
    )
