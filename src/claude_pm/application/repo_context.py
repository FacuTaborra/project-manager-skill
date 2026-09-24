"""Composition of the two config files.

`.pm.toml` says which board this repo writes to; `credentials.toml` says which
token opens it. Everything else here is derived from those two.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.binding import CredentialProfile, ProviderType, RepoBinding, WriteScope
from ..exceptions import ConfigError
from ..infrastructure.config_files.pm_file import load_pm_file
from .profiles import load_profile


@dataclass(frozen=True)
class RepoContext:
    pm_file: RepoBinding
    profile: CredentialProfile

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
            profile_override or pm_file.profile_name, provider=pm_file.provider_type
        )
        _check_provider_match(pm_file, profile)

        return cls(pm_file=pm_file, profile=profile)

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
