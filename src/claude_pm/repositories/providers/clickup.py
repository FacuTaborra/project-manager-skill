"""ClickUp onto the tracker model: Space→Team, List→Project, Task→Issue, Status→State, Tag→Label."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...exceptions import ProviderError
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
from .http_client import HttpClient

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"
CLICKUP_API_V3_BASE = "https://api.clickup.com/api/v3"

_CLOSED_STATUS_TYPES = {"done", "closed"}
# ClickUp's parent type for "the workspace itself" when creating a doc.
_DOC_PARENT_TYPE_WORKSPACE = 4
_MARKDOWN_FORMAT = "text/md"
_DEFAULT_PAGE_TITLE = "Update"


class ClickUpProvider:
    """Personal API Tokens go in the Authorization header without a `Bearer` prefix.

    The workspace is pinned from `.pm.toml`, never discovered: picking `teams[0]` made the board
    you wrote to depend on the order ClickUp returned them.
    """

    def __init__(
        self,
        token: str,
        *,
        workspace_id: str | None = None,
        http: HttpClient | None = None,
        auth_hint: str = "",
    ) -> None:
        self._http = http or HttpClient(headers={"Authorization": token}, auth_hint=auth_hint)
        self._workspace_id = workspace_id

    def _get(self, path: str) -> Any:
        return self._http.get_json(f"{CLICKUP_API_BASE}/{path}")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._http.post_json(f"{CLICKUP_API_BASE}/{path}", body)

    def _post_v3(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._http.post_json(f"{CLICKUP_API_V3_BASE}/{path}", body)

    def _put_v3(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._http.put_json(f"{CLICKUP_API_V3_BASE}/{path}", body)

    def _require_workspace_id(self) -> str:
        if not self._workspace_id:
            raise ProviderError(
                "No ClickUp workspace pinned. Run `pm init` in this repo so .pm.toml "
                "declares which workspace to use."
            )

        return self._workspace_id

    def _spaces(self) -> list[dict[str, Any]]:
        data = self._get(f"team/{self._require_workspace_id()}/space?archived=false")
        spaces: list[dict[str, Any]] = data.get("spaces") or []

        return spaces

    def reachable_workspace_ids(self) -> list[str]:
        return [workspace.id for workspace in self.list_workspaces()]

    def list_workspaces(self) -> list[Workspace]:
        teams = self._get("team").get("teams") or []
        return [Workspace(id=str(t["id"]), name=t.get("name", "")) for t in teams]

    def viewer_email(self) -> str:
        email = (self._get("user").get("user") or {}).get("email")
        if not isinstance(email, str):
            raise ProviderError("user.email missing in ClickUp response")

        return email

    def list_teams(self) -> list[Team]:
        return [Team(id=s["id"], name=s["name"], key=s["id"][:8]) for s in self._spaces()]

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        if team_id:
            return self._lists_in_space(team_id)
        return [
            project for space in self._spaces() for project in self._lists_in_space(space["id"])
        ]

    def _lists_in_space(self, space_id: str) -> list[Project]:
        """Folderless lists first, then the lists inside each folder."""
        folderless = self._get(f"space/{space_id}/list?archived=false").get("lists") or []
        folders = self._get(f"space/{space_id}/folder?archived=false").get("folders") or []
        foldered = [list_json for folder in folders for list_json in folder.get("lists") or []]

        return [Project(id=lst["id"], name=lst["name"]) for lst in [*folderless, *foldered]]

    def create_project(self, name: str, team_id: str) -> Project:
        data = self._post(f"space/{team_id}/list", {"name": name})
        return Project(id=data["id"], name=data["name"])

    def list_states(self, team_id: str) -> list[State]:
        lists = self._lists_in_space(team_id)
        if not lists:
            return []
        statuses = self._get(f"list/{lists[0].id}").get("statuses") or []

        return [State(id=s["status"], name=s["status"]) for s in statuses]

    def list_labels(self, team_id: str) -> list[Label]:
        """ClickUp tags have no id of their own, so the name is the id, as with statuses."""
        tags = self._get(f"space/{team_id}/tag").get("tags") or []
        return [Label(id=t["name"], name=t["name"]) for t in tags]

    def resolve_user_by_email(self, email: str) -> User | None:
        workspace_id = self._require_workspace_id()
        for workspace in self._get("team").get("teams") or []:
            if str(workspace.get("id")) != workspace_id:
                continue
            for member in workspace.get("members") or []:
                user = member.get("user") or {}
                if user.get("email") == email:
                    return User(
                        id=str(user["id"]),
                        email=user["email"],
                        name=user.get("username", ""),
                    )

        return None

    def list_open_issues(self, project_id: str) -> list[Issue]:
        data = self._get(f"list/{project_id}/task?archived=false&include_closed=false")
        return [_to_issue(t) for t in data.get("tasks") or [] if not _is_done(t)]

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]:
        workspace_id = self._require_workspace_id()
        path = f"team/{workspace_id}/task?query={quote(query, safe='')}"
        if project_id:
            path += f"&list_ids[]={quote(project_id, safe='')}"
        tasks = self._get(path).get("tasks") or []

        return [_to_issue(t, with_project=True) for t in tasks]

    def create_issue(self, draft: IssueDraft) -> Issue:
        body: dict[str, Any] = {
            "name": draft.title,
            "markdown_description": draft.description,
        }
        if draft.state_id:
            body["status"] = draft.state_id
        if draft.priority is not None:
            body["priority"] = draft.priority
        if draft.assignee_id:
            body["assignees"] = [_member_id(draft.assignee_id)]
        if draft.label_ids:
            body["tags"] = list(draft.label_ids)

        return _to_issue(self._post(f"list/{draft.project_id}/task", body))

    def get_issue(self, issue_id: str) -> Issue:
        data = self._get(f"task/{issue_id}?include_markdown_description=true")
        return _to_issue(data, with_project=True, with_description=True)

    def update_issue(self, update: IssueUpdate) -> Issue:
        body: dict[str, Any] = {}
        if update.title is not None:
            body["name"] = update.title
        if update.description is not None:
            body["markdown_description"] = update.description
        if update.state_id is not None:
            body["status"] = update.state_id
        if update.priority is not None:
            body["priority"] = update.priority
        if update.assignee_id is not None:
            body["assignees"] = {"add": [_member_id(update.assignee_id)]}

        return _to_issue(self._http.put_json(f"{CLICKUP_API_BASE}/task/{update.issue_id}", body))

    def create_team(self, name: str) -> Team:
        raise ProviderError("ClickUp does not support creating Spaces via API. Use the ClickUp UI.")

    def create_doc(self, title: str, content: str | None = None) -> Doc:
        workspace_id = self._require_workspace_id()
        data = self._post_v3(
            f"workspaces/{workspace_id}/docs",
            {"title": title, "parent": {"id": workspace_id, "type": _DOC_PARENT_TYPE_WORKSPACE}},
        )
        doc_data = data.get("doc") or data
        doc = Doc(id=doc_data["id"], title=doc_data["title"], url=doc_data.get("url"))
        if content:
            self._post_v3(
                f"workspaces/{workspace_id}/docs/{doc.id}/pages",
                {"title": title, "content": content, "content_format": _MARKDOWN_FORMAT},
            )

        return doc

    def update_doc(
        self,
        doc_id: str,
        title: str | None = None,
        content: str | None = None,
        page_id: str | None = None,
    ) -> Doc:
        workspace_id = self._require_workspace_id()
        doc_data: dict[str, Any] = {"id": doc_id, "title": ""}
        if title:
            doc_data = self._put_v3(f"workspaces/{workspace_id}/docs/{doc_id}", {"title": title})
            doc_data = doc_data.get("doc") or doc_data
        if content:
            if page_id:
                self._put_v3(
                    f"workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}",
                    {"content": content, "content_format": _MARKDOWN_FORMAT},
                )
            else:
                self._post_v3(
                    f"workspaces/{workspace_id}/docs/{doc_id}/pages",
                    {
                        "title": title or _DEFAULT_PAGE_TITLE,
                        "content": content,
                        "content_format": _MARKDOWN_FORMAT,
                    },
                )

        return Doc(id=doc_id, title=doc_data.get("title", ""), url=doc_data.get("url"))


def _member_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ProviderError(f"ClickUp member ids are numeric, got {raw!r}.") from None


def _is_done(task: dict[str, Any]) -> bool:
    status = task.get("status") or {}
    return (status.get("type") or "").lower() in _CLOSED_STATUS_TYPES


def _to_issue(
    task: dict[str, Any], *, with_project: bool = False, with_description: bool = False
) -> Issue:
    status_name = (task.get("status") or {}).get("status", "Unknown")
    project: Project | None = None
    if with_project:
        lst = task.get("list")
        if lst:
            project = Project(id=lst["id"], name=lst["name"])

    return Issue(
        identifier=str(task.get("id", "")),
        title=task.get("name", "(untitled)"),
        state=State(id=status_name, name=status_name),
        priority=_map_priority(task.get("priority")),
        url=task.get("url"),
        project=project,
        description=(task.get("markdown_description") or task.get("description"))
        if with_description
        else None,
    )


def _map_priority(p: Any) -> int:
    if not p:
        return 0
    val = p.get("id") if isinstance(p, dict) else p
    try:
        return int(val) if val is not None else 0
    except (TypeError, ValueError):
        return 0
