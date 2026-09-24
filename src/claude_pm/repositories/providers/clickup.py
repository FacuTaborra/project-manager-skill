"""ClickUp adapter — implements the IssueProvider port via ClickUp's REST API v2.

Hierarchy mapping:
  ClickUp Workspace (Team in API) — auto-discovered, usually one per account
  ClickUp Space                   → Team in pm skill
  ClickUp List                    → Project in pm skill
  ClickUp Task                    → Issue in pm skill
  ClickUp Status                  → State in pm skill
"""

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

# ClickUp task statuses that are considered "done" — excluded from briefing
_CLOSED_STATUS_TYPES = {"done", "closed"}


class ClickUpProvider:
    """Implements IssueProvider against ClickUp's REST API v2.

    ClickUp Personal API Tokens are passed directly in the Authorization header
    without a Bearer prefix.
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
        # Pinned from config, never discovered. Picking `teams[0]` meant the board
        # you wrote to depended on the order ClickUp happened to return.
        self._workspace_id = workspace_id

    # -- low-level REST ------------------------------------------------------

    def _get(self, path: str) -> Any:
        return self._http.get_json(f"{CLICKUP_API_BASE}/{path}")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        result = self._http.post_json(f"{CLICKUP_API_BASE}/{path}", body)
        if not isinstance(result, dict):
            raise ProviderError(f"Unexpected ClickUp response: {type(result).__name__}")
        return result

    def _post_v3(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        result = self._http.post_json(f"{CLICKUP_API_V3_BASE}/{path}", body)
        if not isinstance(result, dict):
            raise ProviderError(f"Unexpected ClickUp v3 response: {type(result).__name__}")
        return result

    def _require_workspace_id(self) -> str:
        if not self._workspace_id:
            raise ProviderError(
                "No ClickUp workspace pinned. Run `pm init` in this repo so .pm.toml "
                "declares which workspace to use."
            )
        return self._workspace_id

    def reachable_workspace_ids(self) -> list[str]:
        return [str(t["id"]) for t in self._get("team").get("teams") or []]

    def list_workspaces(self) -> list[Workspace]:
        """Discovery only — `pm init` uses it to let the user pick."""
        teams = self._get("team").get("teams") or []
        return [Workspace(id=str(t["id"]), name=t.get("name", "")) for t in teams]

    # -- IssueProvider methods -----------------------------------------------

    def viewer_email(self) -> str:
        data = self._get("user")
        user = data.get("user") or {}
        email = user.get("email")
        if not isinstance(email, str):
            raise ProviderError("user.email missing in ClickUp response")
        return email

    def list_teams(self) -> list[Team]:
        workspace_id = self._require_workspace_id()
        data = self._get(f"team/{workspace_id}/space?archived=false")
        spaces = data.get("spaces") or []
        return [Team(id=s["id"], name=s["name"], key=s["id"][:8]) for s in spaces]

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        if team_id:
            return self._lists_in_space(team_id)
        workspace_id = self._require_workspace_id()
        data = self._get(f"team/{workspace_id}/space?archived=false")
        spaces = data.get("spaces") or []
        result: list[Project] = []
        for space in spaces:
            result.extend(self._lists_in_space(space["id"]))
        return result

    def _lists_in_space(self, space_id: str) -> list[Project]:
        lists: list[Project] = []
        # Folderless lists
        data = self._get(f"space/{space_id}/list?archived=false")
        for list_json in data.get("lists") or []:
            lists.append(Project(id=list_json["id"], name=list_json["name"]))
        # Lists inside folders
        folders = self._get(f"space/{space_id}/folder?archived=false").get("folders") or []
        for folder in folders:
            for list_json in folder.get("lists") or []:
                lists.append(Project(id=list_json["id"], name=list_json["name"]))
        return lists

    def create_project(self, name: str, team_id: str) -> Project:
        data = self._post(f"space/{team_id}/list", {"name": name})
        return Project(id=data["id"], name=data["name"])

    def list_states(self, team_id: str) -> list[State]:
        lists = self._lists_in_space(team_id)
        if not lists:
            return []
        data = self._get(f"list/{lists[0].id}")
        statuses = data.get("statuses") or []
        return [State(id=s["status"], name=s["status"]) for s in statuses]

    def list_labels(self, team_id: str) -> list[Label]:
        """ClickUp tags, which live on the space — the same granularity `team_id` is.

        Tags have no id of their own: the name is the identity. Using the name as
        the id matches what this adapter already does for statuses, and lets the
        shared label-resolution code work unchanged.
        """
        data = self._get(f"space/{team_id}/tag")
        return [Label(id=t["name"], name=t["name"]) for t in data.get("tags") or []]

    def resolve_user_by_email(self, email: str) -> User | None:
        workspace_id = self._require_workspace_id()
        data = self._get("team")
        workspaces = data.get("teams") or []
        for workspace in workspaces:
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
        tasks = data.get("tasks") or []
        return [_to_issue(t) for t in tasks if not _is_done(t)]

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]:
        workspace_id = self._require_workspace_id()
        path = f"team/{workspace_id}/task?query={quote(query, safe='')}"
        if project_id:
            path += f"&list_ids[]={quote(project_id, safe='')}"
        data = self._get(path)
        tasks = data.get("tasks") or []
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
            # In ClickUp a label id *is* its name; the API takes names here.
            body["tags"] = list(draft.label_ids)

        data = self._post(f"list/{draft.project_id}/task", body)
        return _to_issue(data)

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

        data = self._http.put_json(
            f"{CLICKUP_API_BASE}/task/{update.issue_id}",
            body,
        )
        return _to_issue(data)

    def create_team(self, name: str) -> Team:
        raise ProviderError("ClickUp does not support creating Spaces via API. Use the ClickUp UI.")

    def create_doc(self, title: str, content: str | None = None) -> Doc:
        workspace_id = self._require_workspace_id()
        payload: dict[str, Any] = {
            "title": title,
            "parent": {"id": workspace_id, "type": 4},
        }
        data = self._post_v3(f"workspaces/{workspace_id}/docs", payload)
        doc_data = data.get("doc") or data
        doc = Doc(id=doc_data["id"], title=doc_data["title"], url=doc_data.get("url"))
        if content:
            self._post_v3(
                f"workspaces/{workspace_id}/docs/{doc.id}/pages",
                {"title": title, "content": content, "content_format": "text/md"},
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
            doc_data = self._http.put_json(
                f"{CLICKUP_API_V3_BASE}/workspaces/{workspace_id}/docs/{doc_id}",
                {"title": title},
            )
            doc_data = doc_data.get("doc") or doc_data
        if content:
            if page_id:
                self._http.put_json(
                    f"{CLICKUP_API_V3_BASE}/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}",
                    {"content": content, "content_format": "text/md"},
                )
            else:
                self._post_v3(
                    f"workspaces/{workspace_id}/docs/{doc_id}/pages",
                    {"title": title or "Update", "content": content, "content_format": "text/md"},
                )
        return Doc(id=doc_id, title=doc_data.get("title", ""), url=doc_data.get("url"))


def _member_id(raw: str) -> int:
    """ClickUp member ids are numeric; a bare int() here escaped as a traceback."""
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
    status_node = task.get("status") or {}
    status_name = status_node.get("status", "Unknown")
    state = State(id=status_name, name=status_name)
    project: Project | None = None
    if with_project:
        lst = task.get("list")
        if lst:
            project = Project(id=lst["id"], name=lst["name"])
    return Issue(
        identifier=str(task.get("id", "")),
        title=task.get("name", "(untitled)"),
        state=state,
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
