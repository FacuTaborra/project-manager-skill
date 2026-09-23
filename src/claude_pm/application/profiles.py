"""Shared by `pm creds add` and the `pm init` wizard.

Proving a token works, and deciding which tracker a repo means when nobody
said so outright, are the two pieces of workflow both commands need. Living
here rather than in one command module or the other is what lets `init` add a
first credential without importing `commands/creds.py`.
"""

from __future__ import annotations

from ..credentials import list_profiles
from ..domain.models import Team
from ..enums import ProviderType
from ..exceptions import NeedsChoice, PMError, ProviderError
from ..infrastructure.providers._registry import get_provider


def verify_token(provider: ProviderType, token: str) -> tuple[str, list[Team]]:
    """Prove the token works before it is written anywhere.

    A mistyped token fails here, next to the paste that caused it, instead of
    three commands later where the error no longer looks like its cause.
    """
    probe = get_provider(provider, api_key=token)
    try:
        return probe.viewer_email(), probe.list_workspaces()
    except ProviderError as exc:
        raise PMError(f"That token does not work: {exc}") from exc


def pick_workspace(declared: str | None, reachable: list[Team]) -> str | None:
    """Pin the profile only when there is no doubt; `pm init` asks otherwise."""
    if declared:
        if not any(w.id == declared for w in reachable):
            seen = ", ".join(f"{w.name} ({w.id})" for w in reachable) or "(none)"
            raise PMError(f"That token cannot reach workspace {declared}. It reaches: {seen}.")
        return declared
    return reachable[0].id if len(reachable) == 1 else None


def infer_provider(
    provider: str | None,
    profile: str | None,
    legacy_provider: str | None,
) -> ProviderType:
    """Work out the provider without making the user state the obvious.

    A credential profile already carries one, so naming a profile — or having
    only profiles of one kind — settles it. Only a genuine ambiguity is worth
    asking about, and then it is exit 2 like every other choice, not a dead end.
    """
    raw = provider or legacy_provider
    if raw is not None:
        return ProviderType.parse(raw)

    profiles = list_profiles()
    if profile:
        named = next((p for p in profiles if p.name == profile), None)
        if named is None:
            available = ", ".join(p.name for p in profiles) or "(none)"
            raise PMError(f"Profile {profile!r} not found. Available: {available}.")
        return named.provider

    providers = {p.provider for p in profiles}
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
