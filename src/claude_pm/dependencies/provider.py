from __future__ import annotations

from ..models.repo_config import RepoConfig
from ..repositories.providers.base import IssueProvider
from ..repositories.providers.factory import create_provider


def get_provider(config: RepoConfig) -> IssueProvider:
    profile = config.profile

    return create_provider(
        config.provider_type,
        token=profile.token,
        workspace_id=config.scope.workspace_id,
        auth_hint=(
            f"Credential profile {profile.name!r} was rejected for workspace "
            f"{config.scope.workspace_id} declared in {config.pm_file.path}. Replace the token "
            f"with `pm creds add --name {profile.name} --provider {profile.provider_type.value} "
            "--force`, or run `pm doctor`."
        ),
    )
