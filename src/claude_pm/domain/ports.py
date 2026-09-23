"""Ports — Protocols defining what an issue tracker / context source must provide."""

from __future__ import annotations

from typing import Protocol

from .models import Issue, IssueDraft, IssueUpdate, Label, Project, State, Team, User


class IssueProvider(Protocol):
    """Adapter contract for any issue tracker (Linear, GitHub, Jira, ...).

    Implementations live in pm.infrastructure.providers and are wired through
    pm.infrastructure.providers._registry. To add a new provider, see
    CONTRIBUTING.md.
    """

    def viewer_email(self) -> str:
        """Return the email of the authenticated user (used by `doctor`)."""
        ...

    def workspace_ids(self) -> list[str]:
        """Workspaces/organizations this token can reach.

        Linear returns its single `organization.id`, ClickUp every team id. The
        scope guard compares this against the workspace declared in `.pm.toml`,
        so a rotated or mismatched token is caught before anything is written.
        """
        ...

    def list_workspaces(self) -> list[Team]:
        """Workspaces with their names — discovery only, for `pm init`."""
        ...

    def list_teams(self) -> list[Team]:
        """List all teams the authenticated user belongs to."""
        ...

    def create_team(self, name: str) -> Team:
        """Create a new team."""
        ...

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        """List projects, optionally filtered by team."""
        ...

    def create_project(self, name: str, team_id: str) -> Project:
        """Create a new project in the given team."""
        ...

    def list_states(self, team_id: str) -> list[State]:
        """List workflow states defined for the given team."""
        ...

    def list_labels(self, team_id: str) -> list[Label]:
        """List labels defined for the given team."""
        ...

    def resolve_user_by_email(self, email: str) -> User | None:
        """Find a workspace member by email. Returns None if not found."""
        ...

    def list_open_issues(self, project_id: str) -> list[Issue]:
        """List non-closed issues in the project."""
        ...

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]:
        """Full-text search. If project_id is provided, scope results to that project."""
        ...

    def create_issue(self, draft: IssueDraft) -> Issue:
        """Create a new issue from the given draft."""
        ...

    def get_issue(self, issue_id: str) -> Issue:
        """Fetch a single issue by ID or identifier, including its description."""
        ...

    def update_issue(self, update: IssueUpdate) -> Issue:
        """Update an existing issue. Only fields set (not None) are changed."""
        ...


class ContextProvider(Protocol):
    """Read-only context source enriching briefings (Obsidian vault today)."""

    def is_available(self) -> bool:
        """Whether this context source is reachable / configured."""
        ...

    def get_status_excerpt(self, repo_name: str, max_chars: int = 1500) -> str | None:
        """Return a short excerpt of the project's status, or None if unavailable."""
        ...
