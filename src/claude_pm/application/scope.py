"""The single chokepoint for every write.

This module is the only place in the codebase allowed to call the mutating
methods of `IssueProvider` — `tests/test_scope_invariants.py` enforces that by
inspection. Two things follow from it:

  * nothing can write to a destination the repo has not declared in `.pm.toml`,
    because `_authorized_project_id` is the only code that hands out a writable
    project id;
  * `--dry-run` is total rather than best-effort, because there is no second
    path to the API to forget about.

The old arrangement pushed this job onto prose in SKILL.md. Prose is advice to a
model; this is a precondition.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..domain.binding import IssueDefaults, WriteScope
from ..domain.models import Doc, Issue, IssueDraft, IssueUpdate, Project, Team
from ..domain.ports import DocProvider, IssueProvider
from ..exceptions import NeedsChoice, PMError, ScopeViolation
from ..infrastructure.cache import Cache
from .repo_context import RepoContext


@dataclass(frozen=True)
class DryRun:
    """What a mutation would have done. Returned instead of calling the API."""

    action: str
    destination: str
    list_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "action": self.action,
            "destination": self.destination,
            "list_id": self.list_id,
            "payload": self.payload,
        }


WriteResult = TypeVar("WriteResult")


@dataclass
class ScopeGuard:
    provider: IssueProvider
    scope: WriteScope
    cache: Cache
    defaults: IssueDefaults = field(default_factory=IssueDefaults)
    dry_run: bool = False
    allow_structural_changes: bool = False
    _owning_project_by_issue: dict[str, tuple[str | None, str]] = field(
        default_factory=dict, init=False
    )

    # -- the chokepoint ------------------------------------------------------

    def _authorized_project_id(
        self, action: str, *, project_id: str | None = None, issue_id: str | None = None
    ) -> str:
        """Return the project id this mutation may touch, or refuse.

        The only function in the codebase that grants write permission.
        """
        if issue_id is not None:
            owner_id, owner_name = self._owning_project(issue_id)
            if owner_id is None:
                raise ScopeViolation(
                    f"{action}: {issue_id} belongs to no project, so this repo's scope "
                    f"({self.scope.describe()}) cannot cover it. Refusing to touch it."
                )
            if owner_id not in self.scope.project_ids:
                raise ScopeViolation(
                    f"{action}: {issue_id} lives in {owner_name or owner_id}, outside this "
                    f"repo's scope ({self.scope.describe()}). Refusing to touch it."
                )
            return owner_id

        if project_id is None:
            if len(self.scope.projects) == 1:
                return self.scope.projects[0].id
            raise NeedsChoice(
                "This repo has several lists in scope. Re-run with --project-id <ID>.",
                {
                    "action": "choose-project",
                    "projects": [{"id": ref.id, "name": ref.name} for ref in self.scope.projects],
                },
            )

        if project_id not in self.scope.project_ids:
            allowed = ", ".join(f"{r.name or r.id} ({r.id})" for r in self.scope.projects)
            raise ScopeViolation(
                f"{action}: {project_id} is not in this repo's scope. Allowed: {allowed}. "
                f"If the board really changed, re-run `pm init --force`."
            )
        return project_id

    def _owning_project(self, issue_id: str) -> tuple[str | None, str]:
        """Which project an issue belongs to. One GET, memoized per process."""
        if issue_id not in self._owning_project_by_issue:
            issue = self.provider.get_issue(issue_id)
            project = issue.project
            self._owning_project_by_issue[issue_id] = (
                (project.id, project.name) if project else (None, "")
            )
        return self._owning_project_by_issue[issue_id]

    def _require_structural(self, action: str) -> None:
        if not self.allow_structural_changes:
            raise ScopeViolation(
                f"{action} changes the board's structure and is off by default. "
                f"Re-run with --allow-structural-changes if that is really what you want."
            )

    def _mutate(
        self,
        action: str,
        *,
        project_id: str | None,
        payload: dict[str, Any],
        perform_write: Callable[[], WriteResult],
    ) -> WriteResult | DryRun:
        """Run the write, or describe it instead when this is a dry run.

        Every public write ends here, after its own check has passed. Keeping
        the branch in one place is what makes `--dry-run` total: a new write
        cannot forget it without also skipping this helper, which review sees.
        """
        if self.dry_run:
            return DryRun(
                action=action,
                destination=self._destination_label(project_id),
                list_id=project_id,
                payload=payload,
            )
        return perform_write()

    def _require_doc_provider(self, action: str) -> DocProvider:
        """The provider as a docs-capable one, or a refusal that says why.

        Checked in dry runs too, so a preview never promises a write the
        tracker cannot perform.
        """
        if not isinstance(self.provider, DocProvider):
            raise PMError(
                f"{action} needs a tracker with Docs, and this repo's provider has none. "
                f"Docs are supported on ClickUp only."
            )
        return self.provider

    def _destination_label(self, project_id: str | None) -> str:
        project_label = self.cache.project_name(project_id or "") if project_id else None
        if not project_label and project_id:
            project_label = next((r.name for r in self.scope.projects if r.id == project_id), None)
        project_label = project_label or project_id or "(workspace)"
        workspace_label = self.scope.workspace_name or self.scope.workspace_id
        team_label = self.scope.team_name or self.scope.team_id
        return f"{workspace_label} → {team_label} → {project_label}"

    # -- writes --------------------------------------------------------------

    def create_issue(
        self,
        *,
        title: str,
        description: str,
        project_id: str | None = None,
        state: str | None = None,
        priority: int | None = None,
        assignee_email: str | None = None,
        labels: Sequence[str] = (),
    ) -> Issue | DryRun:
        authorized_project_id = self._authorized_project_id("create-issue", project_id=project_id)

        state_name = state or self.defaults.state
        effective_priority = priority if priority is not None else self.defaults.priority
        label_names = self.merge_labels(labels)

        draft = IssueDraft(
            title=title,
            description=description,
            project_id=authorized_project_id,
            team_id=self.scope.team_id,
            state_id=self.resolve_state_id(state_name),
            priority=effective_priority,
            assignee_id=self.resolve_assignee_id(assignee_email),
            label_ids=self.resolve_label_ids(label_names),
        )
        return self._mutate(
            "create-issue",
            project_id=authorized_project_id,
            payload={
                "title": title,
                "description": description,
                "state": state_name,
                "priority": effective_priority,
                "assignee": assignee_email,
                "labels": list(label_names),
            },
            perform_write=lambda: self.provider.create_issue(draft),
        )

    def update_issue(
        self,
        *,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state: str | None = None,
        priority: int | None = None,
        assignee_email: str | None = None,
    ) -> Issue | DryRun:
        """Same shape as `create_issue`: names in, ids resolved here.

        The "nothing to update" check runs first because it needs no API call,
        and a request that changes nothing should not cost an ownership lookup.
        """
        requested = (title, description, state or None, priority, assignee_email or None)
        if all(value is None for value in requested):
            raise PMError(
                "Nothing to update. Pass at least one of "
                "--title/--description/--state/--priority/--assignee."
            )

        authorized_project_id = self._authorized_project_id("update-issue", issue_id=issue_id)
        update = IssueUpdate(
            issue_id=issue_id,
            title=title,
            description=description,
            state_id=self.resolve_state_id(state),
            priority=priority,
            assignee_id=self.resolve_assignee_id(assignee_email),
        )
        return self._mutate(
            "update-issue",
            project_id=authorized_project_id,
            payload={
                "id": issue_id,
                "title": title,
                "description": description,
                "state": state,
                "priority": priority,
                "assignee": assignee_email,
            },
            perform_write=lambda: self.provider.update_issue(update),
        )

    def create_doc(self, *, title: str, content: str | None) -> Doc | DryRun:
        """Docs live at workspace level, so there is no list to authorize.

        The workspace pin checked when the guard was built is what keeps them
        in the right account.
        """
        docs = self._require_doc_provider("create-doc")
        return self._mutate(
            "create-doc",
            project_id=None,
            payload={"title": title, "has_content": content is not None},
            perform_write=lambda: docs.create_doc(title, content),
        )

    def update_doc(
        self,
        *,
        doc_id: str,
        title: str | None = None,
        content: str | None = None,
        page_id: str | None = None,
    ) -> Doc | DryRun:
        docs = self._require_doc_provider("update-doc")
        return self._mutate(
            "update-doc",
            project_id=None,
            payload={
                "doc_id": doc_id,
                "title": title,
                "page_id": page_id,
                "has_content": content is not None,
            },
            perform_write=lambda: docs.update_doc(
                doc_id, title=title, content=content, page_id=page_id
            ),
        )

    # -- structural writes, off by default -----------------------------------

    def create_project(self, name: str) -> Project | DryRun:
        self._require_structural("create-project")
        return self._mutate(
            "create-project",
            project_id=None,
            payload={"name": name, "space_id": self.scope.team_id},
            perform_write=lambda: self.provider.create_project(name, self.scope.team_id),
        )

    def create_team(self, name: str) -> Team | DryRun:
        self._require_structural("create-team")
        return self._mutate(
            "create-team",
            project_id=None,
            payload={"name": name},
            perform_write=lambda: self.provider.create_team(name),
        )

    # -- resolution helpers (all reads) --------------------------------------

    def merge_labels(self, explicit_labels: Sequence[str]) -> tuple[str, ...]:
        """Repo defaults first, then explicit ones, de-duplicated case-insensitively.

        Done here so no command can forget it: this is what keeps two repos
        sharing one list distinguishable without anyone passing --label.
        """
        merged: list[str] = []
        seen: set[str] = set()
        for name in (*self.defaults.labels, *explicit_labels):
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(name.strip())
        return tuple(merged)

    def resolve_state_id(self, state_name: str | None) -> str | None:
        if not state_name:
            return None
        for name, state_id in self.cache.state_id_by_name.items():
            if name.lower() == state_name.lower():
                return state_id
        available = ", ".join(self.cache.state_id_by_name) or "(none cached)"
        raise PMError(f"State {state_name!r} not found. Available: {available}.")

    def resolve_assignee_id(self, email: str | None) -> str | None:
        if not email:
            return None
        user = self.provider.resolve_user_by_email(email)
        if not user:
            raise PMError(f"No member with email {email!r} in this workspace.")
        return user.id

    def resolve_label_ids(self, names: Sequence[str]) -> tuple[str, ...]:
        if not names:
            return ()
        label_id_by_name = {lbl["name"].lower(): lbl["id"] for lbl in self.cache.labels}
        if not label_id_by_name:
            label_id_by_name = {
                label.name.lower(): label.id
                for label in self.provider.list_labels(self.scope.team_id)
            }
        resolved: list[str] = []
        for name in names:
            label_id = label_id_by_name.get(name.lower())
            if label_id is None:
                known_names = ", ".join(sorted(label_id_by_name)) or "(none)"
                raise PMError(
                    f"Label {name!r} does not exist in this space. Available: {known_names}. "
                    f"Create the label in the tracker, or remove it from [defaults].labels "
                    f"in .pm.toml."
                )
            resolved.append(label_id)
        return tuple(resolved)


def verify_workspace_pin(config: RepoContext, provider: IssueProvider) -> None:
    """Check the token reaches the declared workspace, before anything else does.

    Called ahead of cache refresh rather than after it: every other request is
    already addressed to the declared workspace, so a mismatch would otherwise
    surface as a raw 401 from the tracker instead of a message that says which
    profile is wrong.
    """
    declared = config.scope.workspace_id
    reachable = provider.reachable_workspace_ids()
    if declared not in reachable:
        raise ScopeViolation(
            f"The token for profile {config.profile.name!r} cannot reach workspace "
            f"{declared} declared in {config.pm_file.path}. "
            f"It reaches: {', '.join(reachable) or '(none)'}. "
            f"Wrong profile for this repo, or the token was rotated."
        )


def build_guard(
    config: RepoContext,
    provider: IssueProvider,
    cache: Cache,
    *,
    dry_run: bool = False,
    allow_structural_changes: bool = False,
    check_workspace_pin: bool = True,
) -> ScopeGuard:
    """Composition root for writes.

    `check_workspace_pin=False` is for callers that already ran
    `verify_workspace_pin`, so the check is not paid for twice.
    """
    if check_workspace_pin:
        verify_workspace_pin(config, provider)
    return ScopeGuard(
        provider=provider,
        scope=config.scope,
        cache=cache,
        defaults=config.pm_file.defaults,
        dry_run=dry_run,
        allow_structural_changes=allow_structural_changes,
    )
