"""The single chokepoint for every write.

This module is the only place in the codebase allowed to call the mutating
methods of `IssueProvider` — `tests/test_scope_invariants.py` enforces that by
inspection. Two things follow from it:

  * nothing can write to a destination the repo has not declared in `.pm.toml`,
    because `_authorize` is the only code that hands out a writable list id;
  * `--dry-run` is total rather than best-effort, because there is no second
    path to the API to forget about.

The old arrangement pushed this job onto prose in SKILL.md. Prose is advice to a
model; this is a precondition.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..domain.models import Doc, Issue, IssueDraft, IssueUpdate, Project, Team
from ..domain.ports import IssueProvider
from ..exceptions import NeedsChoice, PMError, ScopeViolation
from ..infrastructure.cache import Cache
from ..pmfile import Defaults, ScopeSpec


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


Outcome = Issue | Doc | Project | Team | DryRun


@dataclass
class ScopeGuard:
    provider: IssueProvider
    scope: ScopeSpec
    cache: Cache
    defaults: Defaults = field(default_factory=Defaults)
    dry_run: bool = False
    allow_structural: bool = False
    _owners: dict[str, tuple[str, str]] = field(default_factory=dict, init=False)

    # -- the chokepoint ------------------------------------------------------

    def _authorize(
        self, action: str, *, list_id: str | None = None, issue_id: str | None = None
    ) -> str:
        """Return the list id this mutation may touch, or refuse.

        The only function in the codebase that grants write permission.
        """
        if issue_id is not None:
            owner_id, owner_name = self._owning_list(issue_id)
            if owner_id is None:
                raise ScopeViolation(
                    f"{action}: {issue_id} belongs to no project, so this repo's scope "
                    f"({self.scope.describe()}) cannot cover it. Refusing to touch it."
                )
            if owner_id not in self.scope.list_ids:
                raise ScopeViolation(
                    f"{action}: {issue_id} lives in {owner_name or owner_id}, outside this "
                    f"repo's scope ({self.scope.describe()}). Refusing to touch it."
                )
            return owner_id

        if list_id is None:
            if len(self.scope.lists) == 1:
                return self.scope.lists[0].id
            raise NeedsChoice(
                "This repo has several lists in scope. Re-run with --project-id <ID>.",
                {
                    "action": "choose-project",
                    "projects": [{"id": ref.id, "name": ref.name} for ref in self.scope.lists],
                },
            )

        if list_id not in self.scope.list_ids:
            allowed = ", ".join(f"{r.name or r.id} ({r.id})" for r in self.scope.lists)
            raise ScopeViolation(
                f"{action}: {list_id} is not in this repo's scope. Allowed: {allowed}. "
                f"If the board really changed, re-run `pm init --force`."
            )
        return list_id

    def _owning_list(self, issue_id: str) -> tuple[str | None, str]:
        """Which list/project an issue belongs to. One GET, memoized per process."""
        if issue_id not in self._owners:
            issue = self.provider.get_issue(issue_id)
            project = issue.project
            self._owners[issue_id] = (
                (project.id, project.name) if project else (None, "")  # type: ignore[assignment]
            )
        return self._owners[issue_id]

    def _require_structural(self, action: str) -> None:
        if not self.allow_structural:
            raise ScopeViolation(
                f"{action} changes the board's structure and is off by default. "
                f"Re-run with --allow-structural-changes if that is really what you want."
            )

    def _describe(self, list_id: str | None) -> str:
        name = self.cache.list_name(list_id or "") if list_id else None
        if not name and list_id:
            name = next((r.name for r in self.scope.lists if r.id == list_id), None)
        tail = name or list_id or "(workspace)"
        head = self.scope.workspace_name or self.scope.workspace_id
        middle = self.scope.space_name or self.scope.space_id
        return f"{head} → {middle} → {tail}"

    # -- writes --------------------------------------------------------------

    def create_issue(
        self,
        *,
        title: str,
        description: str,
        list_id: str | None = None,
        state: str | None = None,
        priority: int | None = None,
        assignee_email: str | None = None,
        labels: Sequence[str] = (),
    ) -> Issue | DryRun:
        target = self._authorize("create-issue", list_id=list_id)

        state_name = state or self.defaults.state
        effective_priority = priority if priority is not None else self.defaults.priority
        label_names = self.merge_labels(labels)

        draft = IssueDraft(
            title=title,
            description=description,
            project_id=target,
            team_id=self.scope.space_id,
            state_id=self.resolve_state_id(state_name),
            priority=effective_priority,
            assignee_id=self.resolve_assignee_id(assignee_email),
            label_ids=self.resolve_label_ids(label_names),
        )

        if self.dry_run:
            return DryRun(
                action="create-issue",
                destination=self._describe(target),
                list_id=target,
                payload={
                    "title": title,
                    "description": description,
                    "state": state_name,
                    "priority": effective_priority,
                    "assignee": assignee_email,
                    "labels": list(label_names),
                },
            )
        return self.provider.create_issue(draft)

    def update_issue(self, update: IssueUpdate) -> Issue | DryRun:
        target = self._authorize("update-issue", issue_id=update.issue_id)
        if self.dry_run:
            return DryRun(
                action="update-issue",
                destination=self._describe(target),
                list_id=target,
                payload={
                    "id": update.issue_id,
                    "title": update.title,
                    "description": update.description,
                    "state_id": update.state_id,
                    "priority": update.priority,
                    "assignee_id": update.assignee_id,
                },
            )
        return self.provider.update_issue(update)

    def create_doc(self, *, title: str, content: str | None) -> Doc | DryRun:
        if self.dry_run:
            return DryRun(
                action="create-doc",
                destination=self._describe(None),
                list_id=None,
                payload={"title": title, "has_content": content is not None},
            )
        return self.provider.create_doc(title, content)  # type: ignore[attr-defined,no-any-return]

    def update_doc(
        self,
        *,
        doc_id: str,
        title: str | None = None,
        content: str | None = None,
        page_id: str | None = None,
    ) -> Doc | DryRun:
        if self.dry_run:
            return DryRun(
                action="update-doc",
                destination=self._describe(None),
                list_id=None,
                payload={"doc_id": doc_id, "title": title, "page_id": page_id},
            )
        return self.provider.update_doc(  # type: ignore[attr-defined,no-any-return]
            doc_id, title=title, content=content, page_id=page_id
        )

    # -- structural writes, off by default -----------------------------------

    def create_list(self, name: str) -> Project | DryRun:
        self._require_structural("create-project")
        if self.dry_run:
            return DryRun(
                action="create-project",
                destination=self._describe(None),
                list_id=None,
                payload={"name": name, "space_id": self.scope.space_id},
            )
        return self.provider.create_project(name, self.scope.space_id)

    def create_space(self, name: str) -> Team | DryRun:
        self._require_structural("create-team")
        if self.dry_run:
            return DryRun(
                action="create-team",
                destination=self._describe(None),
                list_id=None,
                payload={"name": name},
            )
        return self.provider.create_team(name)

    # -- resolution helpers (all reads) --------------------------------------

    def merge_labels(self, extra: Sequence[str]) -> tuple[str, ...]:
        """Repo defaults first, then explicit ones, de-duplicated case-insensitively.

        Done here so no command can forget it: this is what keeps two repos
        sharing one list distinguishable without anyone passing --label.
        """
        merged: list[str] = []
        seen: set[str] = set()
        for name in (*self.defaults.labels, *extra):
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(name.strip())
        return tuple(merged)

    def resolve_state_id(self, state_name: str | None) -> str | None:
        if not state_name:
            return None
        for name, state_id in self.cache.state_ids.items():
            if name.lower() == state_name.lower():
                return state_id
        available = ", ".join(self.cache.state_ids) or "(none cached)"
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
        available = {lbl["name"].lower(): lbl["id"] for lbl in self.cache.labels}
        if not available:
            available = {
                lbl.name.lower(): lbl.id for lbl in self.provider.list_labels(self.scope.space_id)
            }
        resolved: list[str] = []
        for name in names:
            label_id = available.get(name.lower())
            if label_id is None:
                known = ", ".join(sorted(available)) or "(none)"
                raise PMError(
                    f"Label {name!r} does not exist in this space. Available: {known}. "
                    f"Create it in the tracker, or run `pm setup --ensure-labels "
                    f"--allow-structural-changes`."
                )
            resolved.append(label_id)
        return tuple(resolved)


def verify_workspace_pin(config: Config, provider: IssueProvider) -> None:
    """Check the token reaches the declared workspace, before anything else does.

    Called ahead of cache refresh rather than after it: every other request is
    already addressed to the declared workspace, so a mismatch would otherwise
    surface as a raw 401 from the tracker instead of a message that says which
    profile is wrong.
    """
    declared = config.scope.workspace_id
    reachable = provider.workspace_ids()
    if declared not in reachable:
        raise ScopeViolation(
            f"The token for profile {config.profile.name!r} cannot reach workspace "
            f"{declared} declared in {config.pm_file.path}. "
            f"It reaches: {', '.join(reachable) or '(none)'}. "
            f"Wrong profile for this repo, or the token was rotated."
        )


def build_guard(
    config: Config,
    provider: IssueProvider,
    cache: Cache,
    *,
    dry_run: bool = False,
    allow_structural: bool = False,
    verify_pin: bool = True,
) -> ScopeGuard:
    """Composition root for writes.

    `verify_pin=False` is for callers that already ran `verify_workspace_pin`,
    so the check is not paid for twice.
    """
    if verify_pin:
        verify_workspace_pin(config, provider)
    return ScopeGuard(
        provider=provider,
        scope=config.scope,
        cache=cache,
        defaults=config.pm_file.defaults,
        dry_run=dry_run,
        allow_structural=allow_structural,
    )
