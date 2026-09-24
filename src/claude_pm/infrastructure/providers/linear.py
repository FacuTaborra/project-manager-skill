"""Linear adapter — implements the IssueProvider port via Linear's GraphQL API."""

from __future__ import annotations

from typing import Any

from ...domain.models import (
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
from ...exceptions import ProviderError
from ._http import HttpClient

LINEAR_API_URL = "https://api.linear.app/graphql"

_SEARCH_ISSUES_QUERY = """
query($q: String!) {
  searchIssues(term: $q, first: 20) {
    nodes { identifier title state { id name }
            project { id name } }
  }
}
"""


class LinearProvider:
    """Implements IssueProvider against Linear's GraphQL API.

    Linear's PAK is passed in the Authorization header WITHOUT a Bearer prefix —
    that's specific to Personal API Keys, not OAuth tokens.
    """

    def __init__(
        self,
        token: str,
        *,
        workspace_id: str | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self._http = http or HttpClient(headers={"Authorization": token})
        # Linear routes by team/project, so the pin is never part of a URL here.
        # It is accepted anyway so the guard can verify it the same way for both
        # providers, with no per-provider branching at the call site.
        self._workspace_id = workspace_id

    def _query(self, graphql: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._http.post_json(
            LINEAR_API_URL, {"query": graphql, "variables": variables or {}}
        )
        errors = response.get("errors")
        if errors:
            messages = "; ".join(str(e.get("message", "?")) for e in errors)
            raise ProviderError(f"Linear API returned errors: {messages}")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"Unexpected response shape: {response}")
        return data

    def viewer_email(self) -> str:
        data = self._query("{ viewer { email } }")
        viewer = data.get("viewer") or {}
        email = viewer.get("email")
        if not isinstance(email, str):
            raise ProviderError("viewer.email missing in Linear response")
        return email

    def reachable_workspace_ids(self) -> list[str]:
        return [workspace.id for workspace in self.list_workspaces()]

    def list_workspaces(self) -> list[Workspace]:
        """Linear has exactly one organization per token."""
        data = self._query("{ organization { id name urlKey } }")
        org = data.get("organization") or {}
        if not org.get("id"):
            raise ProviderError("organization.id missing in Linear response")
        return [Workspace(id=org["id"], name=org.get("name", ""))]

    def list_teams(self) -> list[Team]:
        data = self._query("{ teams { nodes { id name key } } }")
        nodes = (data.get("teams") or {}).get("nodes") or []
        return [Team(id=n["id"], name=n["name"], key=n["key"]) for n in nodes]

    def create_team(self, name: str) -> Team:
        data = self._query(
            "mutation($input: TeamCreateInput!) { teamCreate(input: $input) "
            "{ success team { id name key } } }",
            {"input": {"name": name}},
        )
        result = data.get("teamCreate") or {}
        if not result.get("success"):
            raise ProviderError(f"Team creation failed: {result}")
        team = result["team"]
        return Team(id=team["id"], name=team["name"], key=team["key"])

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        data = self._query(
            "{ projects(first: 50) { nodes { id name state url teams { nodes { id } } } } }"
        )
        nodes = (data.get("projects") or {}).get("nodes") or []
        result = []
        for project_node in nodes:
            if team_id:
                team_ids = [t["id"] for t in (project_node.get("teams") or {}).get("nodes", [])]
                if team_id not in team_ids:
                    continue
            result.append(
                Project(
                    id=project_node["id"],
                    name=project_node["name"],
                    status_text=project_node.get("state"),
                    url=project_node.get("url"),
                )
            )
        return result

    def create_project(self, name: str, team_id: str) -> Project:
        data = self._query(
            "mutation($input: ProjectCreateInput!) { projectCreate(input: $input) "
            "{ success project { id name } } }",
            {"input": {"name": name, "teamIds": [team_id]}},
        )
        result = data.get("projectCreate") or {}
        if not result.get("success"):
            raise ProviderError(f"Project creation failed: {result}")
        project = result["project"]
        return Project(id=project["id"], name=project["name"])

    def list_states(self, team_id: str) -> list[State]:
        data = self._query(
            "query($id: ID!) { workflowStates(filter: {team: {id: {eq: $id}}}) "
            "{ nodes { id name } } }",
            {"id": team_id},
        )
        nodes = (data.get("workflowStates") or {}).get("nodes") or []
        return [State(id=n["id"], name=n["name"]) for n in nodes]

    def list_labels(self, team_id: str) -> list[Label]:
        data = self._query(
            "query($id: ID!) { issueLabels(filter: {team: {id: {eq: $id}}}) "
            "{ nodes { id name } } }",
            {"id": team_id},
        )
        nodes = (data.get("issueLabels") or {}).get("nodes") or []
        return [Label(id=n["id"], name=n["name"]) for n in nodes]

    def resolve_user_by_email(self, email: str) -> User | None:
        data = self._query(
            "query($email: String!) { users(filter: {email: {eq: $email}}) "
            "{ nodes { id email name } } }",
            {"email": email},
        )
        nodes = (data.get("users") or {}).get("nodes") or []
        if not nodes:
            return None
        user_node = nodes[0]
        return User(id=user_node["id"], email=user_node["email"], name=user_node["name"])

    def list_open_issues(self, project_id: str) -> list[Issue]:
        graphql = """
        query($id: ID!) {
          issues(filter: {project: {id: {eq: $id}},
                          state: {name: {nin: ["Done", "Canceled", "Cancelled"]}}},
                 first: 100) {
            nodes { identifier title priority url state { id name } }
          }
        }
        """
        data = self._query(graphql, {"id": project_id})
        nodes = (data.get("issues") or {}).get("nodes") or []
        return [_to_issue(n) for n in nodes]

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]:
        data = self._query(_SEARCH_ISSUES_QUERY, {"q": query})
        nodes = (data.get("searchIssues") or {}).get("nodes") or []

        issues = [_to_issue(n, with_project=True) for n in nodes]
        if project_id:
            issues = [i for i in issues if i.project is not None and i.project.id == project_id]
        return issues

    def create_issue(self, draft: IssueDraft) -> Issue:
        issue_input: dict[str, Any] = {
            "teamId": draft.team_id,
            "projectId": draft.project_id,
            "title": draft.title,
            "description": draft.description,
        }
        if draft.state_id:
            issue_input["stateId"] = draft.state_id
        if draft.priority is not None:
            issue_input["priority"] = draft.priority
        if draft.assignee_id:
            issue_input["assigneeId"] = draft.assignee_id
        if draft.label_ids:
            issue_input["labelIds"] = list(draft.label_ids)

        data = self._query(
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) "
            "{ success issue { id identifier url title state { id name } } } }",
            {"input": issue_input},
        )
        result = data.get("issueCreate") or {}
        if not result.get("success"):
            raise ProviderError(f"issueCreate failed: {result}")
        return _to_issue(result["issue"])

    def get_issue(self, issue_id: str) -> Issue:
        data = self._query(
            "query($q: String!) { issues(filter: {identifier: {eq: $q}}) "
            "{ nodes { identifier title priority url description state { id name } "
            "project { id name } } } }",
            {"q": issue_id},
        )
        nodes = (data.get("issues") or {}).get("nodes") or []
        if not nodes:
            raise ProviderError(f"Issue '{issue_id}' not found.")
        return _to_issue(nodes[0], with_project=True, with_description=True)

    def update_issue(self, update: IssueUpdate) -> Issue:
        """Resolves the identifier (e.g. FAC-12) to its UUID before mutating."""
        data = self._query(
            "query($q: String!) { issues(filter: {identifier: {eq: $q}}) { nodes { id } } }",
            {"q": update.issue_id},
        )
        nodes = (data.get("issues") or {}).get("nodes") or []
        if not nodes:
            raise ProviderError(f"Issue '{update.issue_id}' not found.")
        issue_uuid = nodes[0]["id"]

        issue_input: dict[str, Any] = {}
        if update.title is not None:
            issue_input["title"] = update.title
        if update.description is not None:
            issue_input["description"] = update.description
        if update.state_id is not None:
            issue_input["stateId"] = update.state_id
        if update.priority is not None:
            issue_input["priority"] = update.priority
        if update.assignee_id is not None:
            issue_input["assigneeId"] = update.assignee_id

        data = self._query(
            "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) "
            "{ success issue { id identifier url title state { id name } } } }",
            {"id": issue_uuid, "input": issue_input},
        )
        result = data.get("issueUpdate") or {}
        if not result.get("success"):
            raise ProviderError(f"issueUpdate failed: {result}")
        return _to_issue(result["issue"])


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _to_issue(
    node: dict[str, Any], *, with_project: bool = False, with_description: bool = False
) -> Issue:
    state_node = node.get("state") or {}
    state = State(id=state_node.get("id", ""), name=state_node.get("name", "Unknown"))
    project: Project | None = None
    if with_project:
        proj_node = node.get("project")
        if proj_node:
            project = Project(id=proj_node["id"], name=proj_node["name"])
    return Issue(
        identifier=node["identifier"],
        title=node["title"],
        state=state,
        priority=int(node.get("priority", 0) or 0),
        url=node.get("url"),
        project=project,
        description=node.get("description") if with_description else None,
    )
