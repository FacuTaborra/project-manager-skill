"""One token per named profile, so two accounts can coexist and no token lives inside a repo."""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..config import credentials_path
from ..enums import ProviderType
from ..exceptions import ConfigError
from ..models.repo_config import CredentialProfile
from .toml import reject_unknown_keys, toml_string

CREDENTIALS_VERSION = 1

_PROFILE_KEYS = {"provider", "token", "workspace_id"}


def list_profiles(path: Path | None = None) -> list[CredentialProfile]:
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
            f"{target}: unsupported version {version} "
            f"(this build understands {CREDENTIALS_VERSION}). Upgrade pm."
        )

    table = raw.get("profiles", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{target}: [profiles] must be a table.")

    return [_parse_profile(name, entry, target) for name, entry in table.items()]


def _parse_profile(name: str, raw: Any, path: Path) -> CredentialProfile:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [profiles.{name}] must be a table.")
    reject_unknown_keys(raw, _PROFILE_KEYS, path, f"[profiles.{name}]")

    provider_type = ProviderType.parse(
        raw.get("provider"), where=f"{path}: [profiles.{name}]: ", error=ConfigError
    )

    token = raw.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigError(f"{path}: [profiles.{name}].token is missing or empty.")

    workspace_id = raw.get("workspace_id")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise ConfigError(f"{path}: [profiles.{name}].workspace_id must be a string.")

    return CredentialProfile(
        name=name,
        provider_type=provider_type,
        token=token.strip(),
        workspace_id=workspace_id or None,
    )


def write_profiles(
    path: Path,
    entries: Sequence[CredentialProfile],
    *,
    replace: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, stat.S_IRWXU)

    if replace and path.is_file():
        names = {entry.name for entry in entries}
        path.write_text(
            _remove_profile_tables(path.read_text(encoding="utf-8"), names), encoding="utf-8"
        )

    header = (
        ""
        if path.is_file() and path.read_text(encoding="utf-8").strip()
        else f"version = {CREDENTIALS_VERSION}\n"
    )
    blocks = []
    for entry in entries:
        block = (
            f"\n[profiles.{entry.name}]\n"
            f"provider     = {toml_string(entry.provider_type.value)}\n"
            f"token        = {toml_string(entry.token)}\n"
        )
        if entry.workspace_id:
            block += f"workspace_id = {toml_string(entry.workspace_id)}\n"
        blocks.append(block)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + "".join(blocks))

    if sys.platform != "win32":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _remove_profile_tables(text: str, names: set[str]) -> str:
    """Lets `--force` replace a profile instead of appending a duplicate table."""
    kept: list[str] = []
    dropping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            dropping = any(stripped == f"[profiles.{name}]" for name in names)
        if not dropping:
            kept.append(line)

    return "\n".join(kept).rstrip() + "\n"


def insecure_permissions_warning(path: Path | None = None) -> str | None:
    """POSIX only: Windows inherits directory ACLs and has no mode bits worth checking."""
    target = path or credentials_path()
    if sys.platform == "win32" or not target.is_file():
        return None
    if target.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{target} is readable by other users. Run: chmod 600 {target}"

    return None
