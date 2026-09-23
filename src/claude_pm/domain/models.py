"""Domain models — frozen dataclasses representing tracker entities."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    key: str


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    status_text: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class State:
    id: str
    name: str


@dataclass(frozen=True)
class Label:
    id: str
    name: str


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str


@dataclass(frozen=True)
class Issue:
    identifier: str
    title: str
    state: State
    priority: int = 0
    url: str | None = None
    project: Project | None = None
    description: str | None = None


@dataclass(frozen=True)
class IssueDraft:
    title: str
    description: str
    project_id: str
    team_id: str
    state_id: str | None = None
    priority: int | None = None
    assignee_id: str | None = None
    label_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueUpdate:
    issue_id: str
    title: str | None = None
    description: str | None = None
    state_id: str | None = None
    priority: int | None = None
    assignee_id: str | None = None


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    url: str | None = None


@dataclass(frozen=True)
class Briefing:
    repo_name: str
    project_name: str
    issues_by_state: dict[str, list[Issue]] = field(default_factory=dict)
    total_open: int = 0
    vault_excerpt: str | None = None
    vault_available: bool = False
