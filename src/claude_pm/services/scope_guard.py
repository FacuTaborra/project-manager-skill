"""The only module allowed to call the provider's mutating methods (enforced by
tests/test_scope_invariants.py). `_authorized_project_id` is the only thing that grants a
writable id, and `_mutate` is the only place the dry-run branch lives.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..exceptions import NeedsChoice, PMError, ScopeViolation
from ..models.repo_config import IssueDefaults, Scope
from ..models.tracker import Doc, Issue, IssueDraft, IssueUpdate, Project, Team
from ..repositories.providers.base import DocProvider, IssueProvider


@dataclass(frozen=True)
class DryRun:
    action: str
    destination: str
    project_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "action": self.action,
            "destination": self.destination,
            "list_id": self.project_id,
            "payload": self.payload,
        }


WriteResult = TypeVar("WriteResult")


@dataclass
class ScopeGuard:
    provider: IssueProvider
    scope: Scope
    defaults: IssueDefaults = field(default_factory=IssueDefaults)
    dry_run: bool = False
    allow_structural_changes: bool = False
    _owning_project_by_issue: dict[str, tuple[str | None, str]] = field(
        default_factory=dict, init=False
    )

    def _authorized_project_id(
        self, action: str, *, project_id: str | None = None, issue_id: str | None = None
    ) -> str:
        """The only function in the codebase that grants write permission."""
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
        if issue_id not in self._owning_project_by_issue:
            project = self.provider.get_issue(issue_id).project
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
        """Every write ends here, so `--dry-run` cannot be forgotten by a new one."""
        if self.dry_run:
            return DryRun(
                action=action,
                destination=self._destination_label(project_id),
                project_id=project_id,
                payload=payload,
            )
        return perform_write()

    def _require_doc_provider(self, action: str) -> DocProvider:
        """Checked in dry runs too, so a preview never promises a write the tracker cannot do."""
        if not isinstance(self.provider, DocProvider):
            raise PMError(
                f"{action} needs a tracker with Docs, and this repo's provider has none. "
                f"Docs are supported on ClickUp only."
            )
        return self.provider

    def _destination_label(self, project_id: str | None) -> str:
        project_label = (
            next((r.name for r in self.scope.projects if r.id == project_id and r.name), None)
            or project_id
            or "(workspace)"
        )
        workspace_label = self.scope.workspace_name or self.scope.workspace_id
        team_label = self.scope.team_name or self.scope.team_id
        return f"{workspace_label} → {team_label} → {project_label}"

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
        label_names = self._merge_labels(labels)

        draft = IssueDraft(
            title=title,
            description=description,
            project_id=authorized_project_id,
            team_id=self.scope.team_id,
            state_id=self._resolve_state_id(state_name),
            priority=effective_priority,
            assignee_id=self._resolve_assignee_id(assignee_email),
            label_ids=self._resolve_label_ids(label_names),
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
        """The empty-update check runs first so a no-op costs no ownership lookup."""
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
            state_id=self._resolve_state_id(state),
            priority=priority,
            assignee_id=self._resolve_assignee_id(assignee_email),
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
        """Docs live at workspace level; the provider's pinned workspace is what scopes them."""
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

    def _merge_labels(self, explicit_labels: Sequence[str]) -> tuple[str, ...]:
        """Merged here so no command can forget the repo labels that tell shared lists apart."""
        merged: list[str] = []
        seen: set[str] = set()
        for name in (*self.defaults.labels, *explicit_labels):
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(name.strip())
        return tuple(merged)

    def _resolve_state_id(self, state_name: str | None) -> str | None:
        if not state_name:
            return None

        states = self.provider.list_states(self.scope.team_id)
        match = next((s for s in states if s.name.lower() == state_name.lower()), None)
        if match is None:
            available = ", ".join(s.name for s in states) or "(none)"
            raise PMError(f"State {state_name!r} not found. Available: {available}.")

        return match.id

    def _resolve_assignee_id(self, email: str | None) -> str | None:
        if not email:
            return None
        user = self.provider.resolve_user_by_email(email)
        if not user:
            raise PMError(f"No member with email {email!r} in this workspace.")
        return user.id

    def _resolve_label_ids(self, names: Sequence[str]) -> tuple[str, ...]:
        if not names:
            return ()
        label_id_by_name = {
            label.name.lower(): label.id for label in self.provider.list_labels(self.scope.team_id)
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
