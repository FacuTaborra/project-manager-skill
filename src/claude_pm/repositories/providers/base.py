from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...models.tracker import (
    Doc,
    Issue,
    IssueDraft,
    IssueUpdate,
    Label,
    Project,
    State,
    Team,
    User,
    Workspace,
)


class IssueProvider(Protocol):
    def viewer_email(self) -> str: ...

    def reachable_workspace_ids(self) -> list[str]:
        """Linear returns its single `organization.id`, ClickUp every team id."""
        ...

    def list_workspaces(self) -> list[Workspace]:
        """Discovery only, for `pm init`."""
        ...

    def list_teams(self) -> list[Team]: ...

    def create_team(self, name: str) -> Team: ...

    def list_projects(self, team_id: str | None = None) -> list[Project]: ...

    def create_project(self, name: str, team_id: str) -> Project: ...

    def list_states(self, team_id: str) -> list[State]: ...

    def list_labels(self, team_id: str) -> list[Label]: ...

    def resolve_user_by_email(self, email: str) -> User | None: ...

    def list_open_issues(self, project_id: str) -> list[Issue]: ...

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]: ...

    def create_issue(self, draft: IssueDraft) -> Issue: ...

    def get_issue(self, issue_id: str) -> Issue:
        """Accepts an id or an identifier; includes the description."""
        ...

    def update_issue(self, update: IssueUpdate) -> Issue:
        """Only the fields that are not None are changed."""
        ...


@runtime_checkable
class DocProvider(Protocol):
    """Kept out of `IssueProvider` so an adapter without docs is still complete; the guard checks
    for it at runtime and refuses with a readable message instead of an `AttributeError`.
    """

    def create_doc(self, title: str, content: str | None) -> Doc:
        """Create a doc, with a first page when `content` is given."""
        ...

    def update_doc(
        self,
        doc_id: str,
        title: str | None = None,
        content: str | None = None,
        page_id: str | None = None,
    ) -> Doc:
        """Rename a doc, and/or replace a page (or append one when `page_id` is None)."""
        ...
