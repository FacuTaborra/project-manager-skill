"""Credential profile resolution, verification, and storage.

Resolving which profile a run should use, proving a token works, and deciding
which tracker a repo means when nobody said so outright, are the pieces of
workflow `pm creds add` and the `pm init` wizard both need. Living here rather
than in one command module or the other is what lets `init` add a first
credential without importing `commands/creds.py`.

The ambient `LINEAR_API_KEY` / `CLICKUP_API_KEY` variables are deliberately NOT
read: picking up a token from whatever directory you happen to be standing in is
the behaviour this design exists to remove. CI passes `PM_TOKEN` explicitly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..domain.binding import CredentialProfile, ProfileEntry, ProviderType
from ..domain.models import Workspace
from ..exceptions import ConfigError, NeedsChoice, PMError, ProviderError
from ..infrastructure.config_files.credentials_store import (
    credentials_path,
    list_profiles,
    write_profiles,
)
from ..infrastructure.providers._registry import create_provider

_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ENV_TOKEN = "PM_TOKEN"
_ENV_PROFILE = "PM_PROFILE"

_SETUP_HINT = (
    "Add one with `pm creds import` (migrates ~/.claude/secrets/*.env) "
    "or by writing the file yourself."
)


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


def infer_provider(
    provider_arg: str | None,
    profile_name: str | None,
    legacy_provider: str | None,
) -> ProviderType:
    """Work out the provider without making the user state the obvious.

    A credential profile already carries one, so naming a profile — or having
    only profiles of one kind — settles it. Only a genuine ambiguity is worth
    asking about, and then it is exit 2 like every other choice, not a dead end.
    """
    raw = provider_arg or legacy_provider
    if raw is not None:
        return ProviderType.parse(raw)

    profiles = list_profiles()
    if profile_name:
        named = next((p for p in profiles if p.name == profile_name), None)
        if named is None:
            available = ", ".join(p.name for p in profiles) or "(none)"
            raise PMError(f"Profile {profile_name!r} not found. Available: {available}.")
        return named.provider_type

    providers = {p.provider_type for p in profiles}
    if len(providers) == 1:
        return providers.pop()
    if not providers:
        raise PMError(
            "No credential profiles yet, so there is no provider to infer.\n"
            "Run `pm creds add --name <name> --provider clickup --token pk_xxx` first."
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


def load_profile(
    name: str | None,
    *,
    provider: ProviderType | None = None,
    path: Path | None = None,
) -> CredentialProfile:
    """Resolve one profile by name.

    `PM_TOKEN` short-circuits the file entirely, for CI. Otherwise the name comes
    from `.pm.toml` (or `PM_PROFILE`); when neither names one and the file holds
    exactly one profile, that one is used.
    """
    wanted = name or os.environ.get(_ENV_PROFILE)

    env_token = os.environ.get(_ENV_TOKEN)
    if env_token:
        if provider is None:
            raise ConfigError(f"{_ENV_TOKEN} is set but the provider is unknown.")
        return CredentialProfile(
            name=wanted or "env",
            provider_type=provider,
            token=env_token,
            workspace_id=os.environ.get("PM_WORKSPACE_ID"),
        )

    profiles = list_profiles(path)
    if not profiles:
        raise ConfigError(f"No credential profiles in {path or credentials_path()}.\n{_SETUP_HINT}")

    if wanted:
        match = next((p for p in profiles if p.name == wanted), None)
        if match is None:
            available = ", ".join(p.name for p in profiles)
            raise ConfigError(
                f"Credential profile {wanted!r} not found in {path or credentials_path()}. "
                f"Available: {available}."
            )
        return match

    # Offering a Linear profile for a ClickUp repo is not a choice, it is noise.
    candidates = [p for p in profiles if p.provider_type is provider] if provider else profiles
    if not candidates:
        available = ", ".join(f"{p.name} ({p.provider_type.value})" for p in profiles)
        raise ConfigError(
            f"No {provider.value if provider else ''} profile in "
            f"{path or credentials_path()}. Available: {available}.\n"
            f"Add one with `pm creds add --name <name> --provider "
            f"{provider.value if provider else '<provider>'} --token ...`."
        )

    if len(candidates) == 1:
        return candidates[0]

    raise NeedsChoice(
        "Several credential profiles exist and none was named. "
        "Re-run with --profile <NAME>, or set `profile` in .pm.toml.",
        {"action": "choose-profile", "profiles": [p.redacted() for p in candidates]},
    )


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
    write_profiles(target, [ProfileEntry(name, provider, token, workspace_id)], replace=force)
