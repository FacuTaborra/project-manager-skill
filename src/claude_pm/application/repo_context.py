"""Composition of the two config files plus the derived cache location.

`.pm.toml` says which board this repo writes to; `credentials.toml` says which
token opens it. Everything else here is derived from those two.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..domain.binding import CredentialProfile, ProviderType, RepoBinding, WriteScope
from ..exceptions import ConfigError
from ..infrastructure.cache import cache_root
from ..infrastructure.config_files.pm_file import load_pm_file
from .profiles import load_profile

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class RepoContext:
    pm_file: RepoBinding
    profile: CredentialProfile
    cache_path: Path
    fingerprint: str

    @property
    def provider_type(self) -> ProviderType:
        return self.pm_file.provider_type

    @property
    def scope(self) -> WriteScope:
        return self.pm_file.scope

    @property
    def repo_root(self) -> Path:
        return self.pm_file.repo_root

    @classmethod
    def load(
        cls,
        *,
        profile_override: str | None = None,
        start: Path | None = None,
    ) -> RepoContext:
        pm_file = load_pm_file(start)
        profile = load_profile(
            profile_override or pm_file.profile_name,
            provider=pm_file.provider_type,
        )
        _check_provider_match(pm_file, profile)

        fingerprint = _fingerprint(pm_file, profile)

        return cls(
            pm_file=pm_file,
            profile=profile,
            cache_path=cache_root() / f"{_slug(pm_file.repo_root.name)}-{fingerprint}.json",
            fingerprint=fingerprint,
        )

    def require_token(self) -> str:
        if not self.profile.token:
            raise ConfigError(
                f"Credential profile {self.profile.name!r} has no token. "
                "Fix it with `pm creds add --force` or by editing credentials.toml."
            )
        return self.profile.token


def _check_provider_match(pm_file: RepoBinding, profile: CredentialProfile) -> None:
    if profile.provider_type is not pm_file.provider_type:
        raise ConfigError(
            f"{pm_file.path} wants provider {pm_file.provider_type.value!r} but profile "
            f"{profile.name!r} is {profile.provider_type.value!r}. "
            "One of the two is pointing at the wrong place."
        )
    declared = profile.workspace_id
    if declared and declared != pm_file.scope.workspace_id:
        raise ConfigError(
            f"Profile {profile.name!r} belongs to workspace {declared}, but "
            f"{pm_file.path} declares {pm_file.scope.workspace_id}. Wrong profile for this repo."
        )


def _fingerprint(pm_file: RepoBinding, profile: CredentialProfile) -> str:
    """Identity of a (repo, profile, board) triple.

    It is the cache filename, so changing any part of it lands on a different
    file — invalidation falls out for free, with no invalidation logic to get
    wrong. The repo root is in there so two checkouts sharing a basename cannot
    collide.
    """
    scope = pm_file.scope
    material = "|".join(
        [
            pm_file.provider_type.value,
            profile.name,
            scope.workspace_id,
            scope.team_id,
            ",".join(sorted(scope.project_ids)),
            str(pm_file.repo_root.resolve()).lower(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def _slug(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "repo"
