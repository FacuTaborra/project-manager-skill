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

from ..domain.ports import IssueProvider
from ..exceptions import NeedsChoice, PMError
from ..pmfile import Defaults, ListRef, ScopeSpec


@dataclass(frozen=True)
class LegacySection:
    """One `[repo]` section of the old INI file."""

    provider: str | None
    space: str | None
    projects: tuple[str, ...]
    label: str | None


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
    projects = tuple(p.strip() for p in section.get("project", "").split(",") if p.strip())
    return LegacySection(
        provider=section.get("provider") or None,
        space=section.get("space") or None,
        projects=projects,
        label=section.get("label") or None,
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


def resolve_space(
    provider: IssueProvider, *, space_id: str | None, space_name: str | None
) -> tuple[str, str]:
    """Resolve a space by id, else by name (the legacy path), else ask."""
    spaces = provider.list_teams()
    if not spaces:
        raise PMError("This workspace has no spaces/teams.")

    if space_id:
        match = next((s for s in spaces if s.id == space_id), None)
        if match is None:
            raise PMError(f"Space {space_id} not found. {_options(spaces)}")
        return match.id, match.name

    if space_name:
        matches = [s for s in spaces if s.name.lower() == space_name.lower()]
        if not matches:
            raise PMError(f"Space {space_name!r} not found. {_options(spaces)}")
        return matches[0].id, matches[0].name

    if len(spaces) == 1:
        return spaces[0].id, spaces[0].name

    raise NeedsChoice(
        "Several spaces exist. Re-run with --space-id <ID>.",
        {"action": "choose-space", "spaces": [{"id": s.id, "name": s.name} for s in spaces]},
    )


def resolve_lists(
    provider: IssueProvider,
    space_id: str,
    *,
    list_ids: list[str] | None = None,
    list_names: list[str] | None = None,
) -> tuple[ListRef, ...]:
    """Resolve the writable destinations by id, else by name, else ask."""
    projects = provider.list_projects(space_id)
    if not projects:
        raise PMError(f"Space {space_id} has no lists to write to.")

    if list_ids:
        by_id = {p.id: p for p in projects}
        refs = []
        for wanted in list_ids:
            project = by_id.get(wanted)
            if project is None:
                raise PMError(f"List {wanted} not found in this space. {_options(projects)}")
            refs.append(ListRef(id=project.id, name=project.name))
        return tuple(refs)

    if list_names:
        by_name = {p.name.lower(): p for p in projects}
        refs = []
        for wanted in list_names:
            project = by_name.get(wanted.lower())
            if project is None:
                raise PMError(f"List {wanted!r} not found in this space. {_options(projects)}")
            refs.append(ListRef(id=project.id, name=project.name))
        return tuple(refs)

    raise NeedsChoice(
        "Pick the list(s) this repo writes to. Re-run with --list-id <ID> (repeatable).",
        {
            "action": "choose-list",
            "lists": [{"id": p.id, "name": p.name} for p in projects],
        },
    )


def build_scope(
    make_provider: Callable[[str | None], IssueProvider],
    *,
    workspace_id: str | None,
    space_id: str | None = None,
    space_name: str | None = None,
    list_ids: list[str] | None = None,
    list_names: list[str] | None = None,
) -> ScopeSpec:
    """Resolve a full scope, pinning the provider as soon as the workspace is known.

    Takes a factory rather than a provider because the dependency is real: spaces
    cannot be listed until the workspace is decided, and a provider is pinned for
    its whole life.
    """
    resolved_workspace, workspace_name = resolve_workspace(make_provider(None), workspace_id)

    provider = make_provider(resolved_workspace)
    resolved_space, resolved_space_name = resolve_space(
        provider, space_id=space_id, space_name=space_name
    )
    lists = resolve_lists(provider, resolved_space, list_ids=list_ids, list_names=list_names)
    return ScopeSpec(
        workspace_id=resolved_workspace,
        workspace_name=workspace_name,
        space_id=resolved_space,
        space_name=resolved_space_name,
        lists=lists,
    )


def defaults_from_legacy(section: LegacySection | None) -> Defaults:
    """`label:` was parsed and dropped for months. Here it finally lands somewhere."""
    if section is None or not section.label:
        return Defaults()
    return Defaults(labels=(section.label,))


def _options(items: list) -> str:  # type: ignore[type-arg]
    return "Available: " + (", ".join(f"{i.name} ({i.id})" for i in items) or "(none)")
