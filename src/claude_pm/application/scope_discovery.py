"""Resolve a board into a `.pm.toml` scope."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.binding import ScopeProject, WriteScope
from ..domain.ports import IssueProvider
from ..exceptions import NeedsChoice, PMError


def resolve_workspace(provider: IssueProvider, declared: str | None) -> tuple[str, str]:
    """Pick the workspace to pin, asking only when it is genuinely ambiguous."""
    workspaces = provider.list_workspaces()
    if not workspaces:
        raise PMError("This token cannot see any workspace.")

    if declared:
        match = next((w for w in workspaces if w.id == declared), None)
        if match is None:
            seen = ", ".join(f"{w.name} ({w.id})" for w in workspaces)
            raise PMError(f"Token cannot reach workspace {declared}. It reaches: {seen}.")
        return match.id, match.name

    if len(workspaces) == 1:
        return workspaces[0].id, workspaces[0].name

    raise NeedsChoice(
        "Several workspaces are reachable. Re-run with --workspace-id <ID>.",
        {
            "action": "choose-workspace",
            "workspaces": [{"id": w.id, "name": w.name} for w in workspaces],
        },
    )


def resolve_team(provider: IssueProvider, *, team_id: str | None) -> tuple[str, str]:
    teams = provider.list_teams()
    if not teams:
        raise PMError("This workspace has no spaces/teams.")

    if team_id:
        match = next((t for t in teams if t.id == team_id), None)
        if match is None:
            raise PMError(f"Space {team_id} not found. {_options(teams)}")
        return match.id, match.name

    if len(teams) == 1:
        return teams[0].id, teams[0].name

    raise NeedsChoice(
        "Several spaces exist. Re-run with --space-id <ID>.",
        {"action": "choose-space", "spaces": [{"id": t.id, "name": t.name} for t in teams]},
    )


def resolve_projects(
    provider: IssueProvider,
    team_id: str,
    *,
    project_ids: list[str] | None = None,
) -> tuple[ScopeProject, ...]:
    projects = provider.list_projects(team_id)
    if not projects:
        raise PMError(f"Space {team_id} has no lists to write to.")

    if project_ids:
        by_id = {p.id: p for p in projects}
        refs = []
        for wanted in project_ids:
            project = by_id.get(wanted)
            if project is None:
                raise PMError(f"List {wanted} not found in this space. {_options(projects)}")
            refs.append(ScopeProject(id=project.id, name=project.name))
        return tuple(refs)

    raise NeedsChoice(
        "Pick the list(s) this repo writes to. Re-run with --list-id <ID> (repeatable).",
        {
            "action": "choose-list",
            "lists": [{"id": p.id, "name": p.name} for p in projects],
        },
    )


def discover_scope(
    make_provider: Callable[[str | None], IssueProvider],
    *,
    workspace_id: str | None,
    team_id: str | None = None,
    project_ids: list[str] | None = None,
) -> WriteScope:
    """Resolve a full scope, pinning the provider as soon as the workspace is known.

    Takes a factory rather than a provider because the dependency is real: spaces
    cannot be listed until the workspace is decided, and a provider is pinned for
    its whole life.
    """
    resolved_workspace, workspace_name = resolve_workspace(make_provider(None), workspace_id)

    provider = make_provider(resolved_workspace)
    resolved_team_id, resolved_team_name = resolve_team(provider, team_id=team_id)
    projects = resolve_projects(provider, resolved_team_id, project_ids=project_ids)
    return WriteScope(
        workspace_id=resolved_workspace,
        workspace_name=workspace_name,
        team_id=resolved_team_id,
        team_name=resolved_team_name,
        projects=projects,
    )


def _options(items: list) -> str:  # type: ignore[type-arg]
    return "Available: " + (", ".join(f"{i.name} ({i.id})" for i in items) or "(none)")
