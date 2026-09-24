"""Value objects binding a repo to a board, and a credential to a workspace.

`RepoBinding` is the shape `<repo>/.pm.toml` parses into; `CredentialProfile` is
the shape one named entry of `~/.claude/pm/credentials.toml` parses into. Both
live here rather than next to the parsers that build them, so
`application/scope.py` and the other consumers depend on a plain value object
instead of the file-reading code that produced it.

`PM_FILE_VERSION` lives here, not with the `.pm.toml` parser, because
`RepoBinding.version` defaults to it and domain code must not import
infrastructure. The parser imports it back from here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..enums import ProviderType

PM_FILE_VERSION = 1


@dataclass(frozen=True)
class ScopeProject:
    """A writable destination: a ClickUp list or a Linear project."""

    id: str
    name: str


@dataclass(frozen=True)
class WriteScope:
    """The allowlist. Nothing outside it can be written to.

    The `*_name` fields never resolve anything — the ids do. They exist so errors
    can name the board a human recognises, and so drift is detectable when
    someone renames it in the tracker.
    """

    workspace_id: str
    team_id: str
    projects: tuple[ScopeProject, ...]
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
    """Applied to every issue created from this repo."""

    labels: tuple[str, ...] = ()
    state: str | None = None
    priority: int | None = None


@dataclass(frozen=True)
class RepoBinding:
    path: Path
    repo_root: Path
    provider_type: ProviderType
    profile_name: str
    scope: WriteScope
    defaults: IssueDefaults = field(default_factory=IssueDefaults)
    version: int = PM_FILE_VERSION


@dataclass(frozen=True)
class CredentialProfile:
    name: str
    provider_type: ProviderType
    token: str
    workspace_id: str | None = None

    def redacted(self) -> dict[str, Any]:
        """Shape safe to print: enough to identify the token, not to use it."""
        tail = self.token[-4:] if len(self.token) > 8 else ""
        return {
            "name": self.name,
            "provider": self.provider_type.value,
            "workspace_id": self.workspace_id,
            "token": f"…{tail}" if tail else "…",
        }


@dataclass(frozen=True)
class RepoConfig:
    """`.pm.toml` plus the credential it names: everything a command needs to reach the board."""

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
