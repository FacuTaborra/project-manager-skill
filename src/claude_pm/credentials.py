"""Named credential profiles in `~/.claude/pm/credentials.toml`.

One token per profile, each pinned to the workspace it belongs to. A repo's
`.pm.toml` names the profile it wants, so two ClickUp accounts can coexist and
the token never lives inside a repo.

The ambient `LINEAR_API_KEY` / `CLICKUP_API_KEY` variables are deliberately NOT
read: picking up a token from whatever directory you happen to be standing in is
the behaviour this design exists to remove. CI passes `PM_TOKEN` explicitly.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._toml_schema import reject_unknown, toml_string
from .enums import ProviderType
from .exceptions import ConfigError, NeedsChoice, PMError

CREDENTIALS_VERSION = 1

DEFAULT_CREDENTIALS_PATH = Path.home() / ".claude" / "pm" / "credentials.toml"

_PROFILE_KEYS = {"provider", "token", "workspace_id"}
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ENV_TOKEN = "PM_TOKEN"
_ENV_PROFILE = "PM_PROFILE"

_SETUP_HINT = (
    "Add one with `pm creds import` (migrates ~/.claude/secrets/*.env) "
    "or by writing the file yourself."
)

LEGACY_SECRETS = {
    ProviderType.LINEAR: (Path.home() / ".claude" / "secrets" / "linear-pak.env", "LINEAR_API_KEY"),
    ProviderType.CLICKUP: (
        Path.home() / ".claude" / "secrets" / "clickup-pak.env",
        "CLICKUP_API_KEY",
    ),
}


@dataclass(frozen=True)
class Profile:
    name: str
    provider: ProviderType
    token: str
    workspace_id: str | None = None

    def redacted(self) -> dict[str, Any]:
        """Shape safe to print: enough to identify the token, not to use it."""
        tail = self.token[-4:] if len(self.token) > 8 else ""
        return {
            "name": self.name,
            "provider": self.provider.value,
            "workspace_id": self.workspace_id,
            "token": f"…{tail}" if tail else "…",
        }


def credentials_path() -> Path:
    env = os.environ.get("PM_CREDENTIALS_FILE")
    return Path(env).expanduser() if env else DEFAULT_CREDENTIALS_PATH


def load_profile(
    name: str | None,
    *,
    provider: ProviderType | None = None,
    path: Path | None = None,
) -> Profile:
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
        return Profile(
            name=wanted or "env",
            provider=provider,
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
    candidates = [p for p in profiles if p.provider is provider] if provider else profiles
    if not candidates:
        available = ", ".join(f"{p.name} ({p.provider.value})" for p in profiles)
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


def list_profiles(path: Path | None = None) -> list[Profile]:
    """Every profile in the credentials file, in declaration order."""
    target = path or credentials_path()
    if not target.is_file():
        return []
    try:
        raw: dict[str, Any] = tomllib.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read {target}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{target} is not valid TOML: {exc}") from exc

    version = raw.get("version", CREDENTIALS_VERSION)
    if version != CREDENTIALS_VERSION:
        raise ConfigError(
            f"{target}: unsupported version {version} (this build understands {CREDENTIALS_VERSION})."
        )

    table = raw.get("profiles", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{target}: [profiles] must be a table.")

    return [_profile(name, entry, target) for name, entry in table.items()]


def _profile(name: str, raw: Any, path: Path) -> Profile:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [profiles.{name}] must be a table.")
    reject_unknown(raw, _PROFILE_KEYS, path, f"[profiles.{name}]")

    provider = ProviderType.parse(
        raw.get("provider"), where=f"{path}: [profiles.{name}]: ", error=ConfigError
    )

    token = raw.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigError(f"{path}: [profiles.{name}].token is missing or empty.")

    workspace_id = raw.get("workspace_id")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise ConfigError(f"{path}: [profiles.{name}].workspace_id must be a string.")

    return Profile(
        name=name,
        provider=provider,
        token=token.strip(),
        workspace_id=workspace_id or None,
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
    write_profiles(target, [(name, provider, token, workspace_id)], replace=force)


def write_profiles(
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

    header = (
        ""
        if path.is_file() and path.read_text(encoding="utf-8").strip()
        else f"version = {CREDENTIALS_VERSION}\n"
    )
    blocks = []
    for name, provider, token, workspace_id in entries:
        block = (
            f"\n[profiles.{name}]\n"
            f"provider     = {toml_string(provider.value)}\n"
            f"token        = {toml_string(token)}\n"
        )
        if workspace_id:
            block += f"workspace_id = {toml_string(workspace_id)}\n"
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


def find_legacy_tokens() -> list[tuple[str, ProviderType, str, str | None]]:
    """Discover tokens left by the old `~/.claude/secrets/*.env` layout, for `pm creds import`."""
    return [
        (f"{provider.value}-default", provider, token, None)
        for provider, (secret_file, key) in LEGACY_SECRETS.items()
        if (token := _read_env_key(secret_file, key))
    ]


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


def warn_if_world_readable(path: Path | None = None) -> str | None:
    """Return a warning when the credentials file is readable beyond its owner.

    Windows inherits directory ACLs and has no mode bits worth checking, so this
    only reports on POSIX.
    """
    target = path or credentials_path()
    if sys.platform == "win32" or not target.is_file():
        return None
    mode = target.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{target} is readable by other users. Run: chmod 600 {target}"
    return None
