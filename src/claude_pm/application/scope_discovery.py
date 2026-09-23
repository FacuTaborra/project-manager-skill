"""Resolve a board into a `.pm.toml` scope.

Two ways in: pick interactively (via NeedsChoice round-trips, since the caller is
usually Claude and cannot answer a prompt), or convert a section of the legacy
`projects.pm`, which named spaces and projects instead of identifying them.

The legacy path is the one that finally puts `label:` to work: it becomes
`[defaults].labels`, which is what lets two repos share one list and still be
told apart.
"""

from __future__ import annotations

import configparser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.binding import IssueDefaults, ScopeProject, WriteScope
from ..domain.ports import IssueProvider
from ..exceptions import NeedsChoice, PMError


@dataclass(frozen=True)
class LegacySection:
    """One `[repo]` section of the old INI file."""

    provider_name: str | None
    team_name: str | None
    project_names: tuple[str, ...]
    label_name: str | None


def read_legacy_section(path: Path, repo_name: str) -> LegacySection | None:
    if not path.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        raise PMError(f"Cannot read legacy {path}: {exc}") from exc

    name = next((s for s in parser.sections() if s.lower() == repo_name.lower()), None)
    if name is None:
        return None
    section = parser[name]
    project_names = tuple(p.strip() for p in section.get("project", "").split(",") if p.strip())
    return LegacySection(
        provider_name=section.get("provider") or None,
        team_name=section.get("space") or None,
        project_names=project_names,
        label_name=section.get("label") or None,
    )


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


def resolve_team(
    provider: IssueProvider, *, team_id: str | None, team_name: str | None
) -> tuple[str, str]:
    """Resolve a team by id, else by name (the legacy path), else ask."""
    teams = provider.list_teams()
    if not teams:
        raise PMError("This workspace has no spaces/teams.")

    if team_id:
        match = next((t for t in teams if t.id == team_id), None)
        if match is None:
            raise PMError(f"Space {team_id} not found. {_options(teams)}")
        return match.id, match.name

    if team_name:
        matches = [t for t in teams if t.name.lower() == team_name.lower()]
        if not matches:
            raise PMError(f"Space {team_name!r} not found. {_options(teams)}")
        return matches[0].id, matches[0].name

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
    project_names: list[str] | None = None,
) -> tuple[ScopeProject, ...]:
    """Resolve the writable destinations by id, else by name, else ask."""
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

    if project_names:
        by_name = {p.name.lower(): p for p in projects}
        refs = []
        for wanted in project_names:
            project = by_name.get(wanted.lower())
            if project is None:
                raise PMError(f"List {wanted!r} not found in this space. {_options(projects)}")
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
    team_name: str | None = None,
    project_ids: list[str] | None = None,
    project_names: list[str] | None = None,
) -> WriteScope:
    """Resolve a full scope, pinning the provider as soon as the workspace is known.

    Takes a factory rather than a provider because the dependency is real: spaces
    cannot be listed until the workspace is decided, and a provider is pinned for
    its whole life.
    """
    resolved_workspace, workspace_name = resolve_workspace(make_provider(None), workspace_id)

    provider = make_provider(resolved_workspace)
    resolved_team_id, resolved_team_name = resolve_team(
        provider, team_id=team_id, team_name=team_name
    )
    projects = resolve_projects(
        provider, resolved_team_id, project_ids=project_ids, project_names=project_names
    )
    return WriteScope(
        workspace_id=resolved_workspace,
        workspace_name=workspace_name,
        team_id=resolved_team_id,
        team_name=resolved_team_name,
        projects=projects,
    )


def defaults_from_legacy(section: LegacySection | None) -> IssueDefaults:
    """`label:` was parsed and dropped for months. Here it finally lands somewhere."""
    if section is None or not section.label_name:
        return IssueDefaults()
    return IssueDefaults(labels=(section.label_name,))


def _options(items: list) -> str:  # type: ignore[type-arg]
    return "Available: " + (", ".join(f"{i.name} ({i.id})" for i in items) or "(none)")
