"""Composition of the two config files plus the derived cache location.

`.pm.toml` says which board this repo writes to; `credentials.toml` says which
token opens it. Everything else here is derived from those two.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .credentials import Profile, load_profile
from .enums import ProviderType
from .exceptions import ConfigError
from .infrastructure.repo_detect import detect_repo_name
from .pmfile import PmFile, ScopeSpec, load_pm_file

DEFAULT_VAULT = Path.home() / ".claude-memory"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def cache_root() -> Path:
    """Where machine state lives — never the Obsidian vault, which is for humans."""
    env = os.environ.get("PM_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "claude-pm"
    return Path.home() / ".cache" / "claude-pm"


@dataclass(frozen=True)
class Config:
    pm_file: PmFile
    profile: Profile
    repo_name: str
    cache_path: Path
    fingerprint: str
    vault_path: Path | None = None

    @property
    def provider_name(self) -> ProviderType:
        return self.pm_file.provider

    @property
    def scope(self) -> ScopeSpec:
        return self.pm_file.scope

    @property
    def repo_root(self) -> Path:
        return self.pm_file.repo_root

    @classmethod
    def load(
        cls,
        repo_name_override: str | None = None,
        *,
        profile_override: str | None = None,
        start: Path | None = None,
    ) -> Config:
        pm_file = load_pm_file(start)
        profile = load_profile(
            profile_override or pm_file.profile,
            provider=pm_file.provider,
        )
        _check_provider_match(pm_file, profile)

        repo_name = repo_name_override or detect_repo_name(pm_file.repo_root)
        fingerprint = _fingerprint(pm_file, profile)

        return cls(
            pm_file=pm_file,
            profile=profile,
            repo_name=repo_name,
            cache_path=cache_root() / f"{_slug(repo_name)}-{fingerprint}.json",
            fingerprint=fingerprint,
            vault_path=_vault_path(),
        )

    def require_pak(self) -> str:
        if not self.profile.token:
            raise ConfigError(
                f"Credential profile {self.profile.name!r} has no token. "
                "Fix it with `pm creds import` or by editing credentials.toml."
            )
        return self.profile.token


def _check_provider_match(pm_file: PmFile, profile: Profile) -> None:
    if profile.provider is not pm_file.provider:
        raise ConfigError(
            f"{pm_file.path} wants provider {pm_file.provider.value!r} but profile "
            f"{profile.name!r} is {profile.provider.value!r}. "
            "One of the two is pointing at the wrong place."
        )
    declared = profile.workspace_id
    if declared and declared != pm_file.scope.workspace_id:
        raise ConfigError(
            f"Profile {profile.name!r} belongs to workspace {declared}, but "
            f"{pm_file.path} declares {pm_file.scope.workspace_id}. Wrong profile for this repo."
        )


def _fingerprint(pm_file: PmFile, profile: Profile) -> str:
    """Identity of a (repo, profile, board) triple.

    It is the cache filename, so changing any part of it lands on a different
    file — invalidation falls out for free, with no invalidation logic to get
    wrong. The repo root is in there so two checkouts sharing a basename cannot
    collide.
    """
    scope = pm_file.scope
    material = "|".join(
        [
            pm_file.provider.value,
            profile.name,
            scope.workspace_id,
            scope.space_id,
            ",".join(sorted(scope.list_ids)),
            str(pm_file.repo_root.resolve()).lower(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def _slug(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "repo"


def _vault_path() -> Path | None:
    env = os.environ.get("CLAUDE_MEMORY_PATH")
    path = Path(env).expanduser() if env else DEFAULT_VAULT
    return path if path.is_dir() else None
