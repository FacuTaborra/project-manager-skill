from __future__ import annotations

from argparse import Namespace

from ..exceptions import ConfigError
from ..models.repo_config import CredentialProfile, RepoBinding, RepoConfig
from ..repositories.pm_file_repository import load_pm_file
from ..services.credential_service import load_profile


def get_repo_config(args: Namespace) -> RepoConfig:
    pm_file = load_pm_file()
    profile = load_profile(args.profile or pm_file.profile_name, provider=pm_file.provider_type)
    _check_profile_matches(pm_file, profile)

    return RepoConfig(pm_file=pm_file, profile=profile)


def _check_profile_matches(pm_file: RepoBinding, profile: CredentialProfile) -> None:
    if profile.provider_type is not pm_file.provider_type:
        raise ConfigError(
            f"{pm_file.path} wants provider {pm_file.provider_type.value!r} but profile "
            f"{profile.name!r} is {profile.provider_type.value!r}. Pass the right --profile."
        )
    if profile.workspace_id and profile.workspace_id != pm_file.scope.workspace_id:
        raise ConfigError(
            f"Profile {profile.name!r} belongs to workspace {profile.workspace_id}, but "
            f"{pm_file.path} declares {pm_file.scope.workspace_id}. Pass the right --profile."
        )
