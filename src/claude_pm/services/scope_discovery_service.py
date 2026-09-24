"""What `pm init` needs to decide: which credential, workspace, space and lists.

Every choice is resolved the same way: a flag wins, a single option is adopted,
and anything else goes to `pick` — a menu for a person, an error naming the flag
for everyone else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol, TypeVar

from ..enums import ProviderType
from ..exceptions import ConfigError, PMError
from ..models.repo_config import CredentialProfile, ScopeProject, WriteScope
from ..repositories.providers.base import IssueProvider


class Option(NamedTuple):
    id: str
    label: str


Pick = Callable[[str, Sequence[Option], str, bool], list[str]]


class _Named(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


Item = TypeVar("Item", bound=_Named)


def choose_profile(
    profiles: Sequence[CredentialProfile],
    *,
    name: str | None,
    provider: ProviderType | None,
    pick: Pick,
) -> CredentialProfile:
    if not profiles:
        raise ConfigError(
            "No credential profiles yet. Add one with "
            "`pm creds add --name <name> --provider <clickup|linear> --token ...`."
        )

    if name:
        match = next((p for p in profiles if p.name == name), None)
        if match is None:
            raise PMError(
                f"Profile {name!r} not found. Available: {', '.join(p.name for p in profiles)}."
            )
        if provider and match.provider_type is not provider:
            raise PMError(
                f"Profile {name!r} is for {match.provider_type.value}, not {provider.value}."
            )
        return match

    candidates = [p for p in profiles if provider is None or p.provider_type is provider]
    if not candidates:
        raise PMError(
            f"No {provider.value if provider else ''} profile yet. Add one with "
            f"`pm creds add --name <name> --provider {provider.value if provider else '<provider>'}`."
        )
    if len(candidates) == 1:
        return candidates[0]

    [chosen] = pick(
        "Which credential does this repo use?",
        [Option(p.name, f"{p.name} ({p.provider_type.value})") for p in candidates],
        "--profile",
        False,
    )
    return next(p for p in candidates if p.name == chosen)


def discover_scope(
    make_provider: Callable[[str | None], IssueProvider],
    *,
    workspace_id: str | None,
    team_id: str | None,
    project_ids: Sequence[str] | None,
    pick: Pick,
) -> WriteScope:
    """Takes a provider factory because spaces cannot be listed until the workspace is pinned."""
    workspace = _pick_one(
        make_provider(None).list_workspaces(),
        workspace_id,
        pick,
        "Which workspace?",
        "--workspace-id",
    )
    provider = make_provider(workspace.id)
    team = _pick_one(provider.list_teams(), team_id, pick, "Which space?", "--space-id")
    projects = _pick_many(provider.list_projects(team.id), project_ids, pick)

    return WriteScope(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        team_id=team.id,
        team_name=team.name,
        projects=tuple(ScopeProject(id=p.id, name=p.name) for p in projects),
    )


def verify_declared_scope(provider: IssueProvider, scope: WriteScope, source: Path) -> list[str]:
    """Raise if the declared space or a list is gone; return warnings for renamed ones."""
    teams = provider.list_teams()
    team = next((t for t in teams if t.id == scope.team_id), None)
    if team is None:
        raise PMError(
            f"Space {scope.team_id} declared in {source} does not exist. {_available(teams)} "
            "Re-run `pm init --force`."
        )

    warnings = []
    if scope.team_name and team.name.lower() != scope.team_name.lower():
        warnings.append(
            f"Space {team.id} is now named {team.name!r}, {source} says {scope.team_name!r}."
        )

    projects = {p.id: p for p in provider.list_projects(scope.team_id)}
    for ref in scope.projects:
        project = projects.get(ref.id)
        if project is None:
            raise PMError(
                f"List {ref.id} ({ref.name or 'unnamed'}) declared in {source} is not in space "
                f"{team.name}. {_available(list(projects.values()))} Re-run `pm init --force`."
            )
        if ref.name and project.name.lower() != ref.name.lower():
            warnings.append(
                f"List {ref.id} is now named {project.name!r}, {source} says {ref.name!r}."
            )

    return warnings


def _pick_one(
    items: Sequence[Item], wanted: str | None, pick: Pick, question: str, flag: str
) -> Item:
    if not items:
        raise PMError(f"{question} There is nothing to choose from with this token.")
    if wanted:
        return _find(items, wanted)
    if len(items) == 1:
        return items[0]

    [chosen] = pick(question, _as_options(items), flag, False)
    return _find(items, chosen)


def _pick_many(items: Sequence[Item], wanted: Sequence[str] | None, pick: Pick) -> list[Item]:
    if not items:
        raise PMError("This space has no lists to write to.")
    if wanted:
        return [_find(items, item_id) for item_id in wanted]
    if len(items) == 1:
        return [items[0]]

    chosen = pick("Which list(s) does this repo write to?", _as_options(items), "--list-id", True)
    return [_find(items, item_id) for item_id in chosen]


def _find(items: Sequence[Item], item_id: str) -> Item:
    match = next((i for i in items if i.id == item_id), None)
    if match is None:
        raise PMError(f"{item_id} not found. {_available(items)}")
    return match


def _as_options(items: Sequence[Item]) -> list[Option]:
    return [Option(i.id, i.name) for i in items]


def _available(items: Sequence[_Named]) -> str:
    return "Available: " + (", ".join(f"{i.name} ({i.id})" for i in items) or "(none)")
