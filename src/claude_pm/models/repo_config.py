from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..enums import ProviderType


@dataclass(frozen=True)
class ProjectRef:
    """A list (ClickUp) or project (Linear) this repo may write to."""

    id: str
    name: str


@dataclass(frozen=True)
class Scope:
    """The write allowlist. The ids decide; the names only make errors readable."""

    workspace_id: str
    team_id: str
    projects: tuple[ProjectRef, ...]
    workspace_name: str = ""
    team_name: str = ""

    @property
    def project_ids(self) -> frozenset[str]:
        return frozenset(ref.id for ref in self.projects)

    def describe(self) -> str:
        names = ", ".join(ref.name or ref.id for ref in self.projects)
        return f"{self.workspace_name or self.workspace_id} → {self.team_name or self.team_id} → {names}"


@dataclass(frozen=True)
class IssueDefaults:
    labels: tuple[str, ...] = ()
    state: str | None = None
    priority: int | None = None


@dataclass(frozen=True)
class PmFile:
    path: Path
    repo_root: Path
    provider_type: ProviderType
    profile_name: str
    scope: Scope
    defaults: IssueDefaults = field(default_factory=IssueDefaults)


@dataclass(frozen=True)
class CredentialProfile:
    name: str
    provider_type: ProviderType
    token: str
    workspace_id: str | None = None

    def redacted(self) -> dict[str, Any]:
        tail = self.token[-4:] if len(self.token) > 8 else ""

        return {
            "name": self.name,
            "provider": self.provider_type.value,
            "workspace_id": self.workspace_id,
            "token": f"…{tail}" if tail else "…",
        }


@dataclass(frozen=True)
class RepoConfig:
    pm_file: PmFile
    profile: CredentialProfile

    @property
    def provider_type(self) -> ProviderType:
        return self.pm_file.provider_type

    @property
    def scope(self) -> Scope:
        return self.pm_file.scope

    @property
    def repo_root(self) -> Path:
        return self.pm_file.repo_root
