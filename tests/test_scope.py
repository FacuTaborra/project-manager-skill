"""The scope guard: what it refuses, and what it does before it agrees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.claude_pm.application.repo_context import RepoContext
from src.claude_pm.application.scope import (
    DryRun,
    ScopeGuard,
    build_guard,
    verify_workspace_pin,
)
from src.claude_pm.domain.binding import (
    CredentialProfile,
    IssueDefaults,
    ProviderType,
    RepoBinding,
    ScopeProject,
    WriteScope,
)
from src.claude_pm.domain.models import Doc, Issue, IssueUpdate, Label, Project, State, Team, User
from src.claude_pm.exceptions import NeedsChoice, PMError, ScopeViolation

IN_SCOPE = "list-in"
OTHER = "list-out"

SCOPE = WriteScope(
    workspace_id="ws-1",
    workspace_name="Hemisphere",
    team_id="space-1",
    team_name="4plus",
    projects=(ScopeProject(id=IN_SCOPE, name="modulo-energia"),),
)

TWO_LISTS = WriteScope(
    workspace_id="ws-1",
    team_id="space-1",
    projects=(ScopeProject(id=IN_SCOPE, name="a"), ScopeProject(id="list-two", name="b")),
)


class FakeProvider:
    """Records every call so tests can assert on what did and did not happen."""

    def __init__(
        self,
        owners: dict[str, str | None] | None = None,
        reachable: tuple[str, ...] = ("ws-1",),
    ) -> None:
        self.owners = owners or {}
        self.reachable = reachable
        self.calls: list[tuple[str, Any]] = []

    def _issue(self, identifier: str, project_id: str | None) -> Issue:
        return Issue(
            identifier=identifier,
            title="t",
            state=State(id="s", name="Backlog"),
            project=Project(id=project_id, name=f"name-of-{project_id}") if project_id else None,
        )

    def get_issue(self, issue_id: str) -> Issue:
        self.calls.append(("get_issue", issue_id))
        return self._issue(issue_id, self.owners.get(issue_id, IN_SCOPE))

    def create_issue(self, draft: Any) -> Issue:
        self.calls.append(("create_issue", draft))
        return self._issue("NEW-1", draft.project_id)

    def update_issue(self, update: IssueUpdate) -> Issue:
        self.calls.append(("update_issue", update))
        return self._issue(update.issue_id, IN_SCOPE)

    def create_project(self, name: str, team_id: str) -> Project:
        self.calls.append(("create_project", (name, team_id)))
        return Project(id="new-list", name=name)

    def create_team(self, name: str) -> Team:
        self.calls.append(("create_team", name))
        return Team(id="new-space", name=name, key="NEW")

    def resolve_user_by_email(self, email: str) -> User | None:
        self.calls.append(("resolve_user_by_email", email))
        return User(id="42", email=email, name="dev") if "dev@" in email else None

    def list_states(self, team_id: str) -> list[State]:
        self.calls.append(("list_states", team_id))
        return [State(id="Backlog", name="Backlog"), State(id="in progress", name="In Progress")]

    def list_labels(self, team_id: str) -> list[Label]:
        self.calls.append(("list_labels", team_id))
        return [Label(id="alerts-api", name="alerts-api"), Label(id="bug", name="bug")]

    def reachable_workspace_ids(self) -> list[str]:
        self.calls.append(("reachable_workspace_ids", None))
        return list(self.reachable)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _guard(provider: FakeProvider, **kwargs: Any) -> ScopeGuard:
    options: dict[str, Any] = {"scope": SCOPE}
    options.update(kwargs)
    return ScopeGuard(provider=provider, **options)


class TestCreateIssue:
    def test_writes_to_the_only_list_in_scope(self) -> None:
        provider = FakeProvider()
        _guard(provider).create_issue(title="T", description="D")
        draft = dict(provider.calls)["create_issue"]
        assert draft.project_id == IN_SCOPE

    def test_an_explicit_in_scope_list_is_allowed(self) -> None:
        provider = FakeProvider()
        _guard(provider).create_issue(title="T", description="D", project_id=IN_SCOPE)
        assert "create_issue" in provider.names()

    def test_a_list_outside_the_scope_is_refused(self) -> None:
        """The hole that used to let --project-id write to any board."""
        provider = FakeProvider()
        with pytest.raises(ScopeViolation, match="not in this repo's scope"):
            _guard(provider).create_issue(title="T", description="D", project_id=OTHER)
        assert "create_issue" not in provider.names()

    def test_the_refusal_names_what_is_allowed(self) -> None:
        with pytest.raises(ScopeViolation, match="modulo-energia"):
            _guard(FakeProvider()).create_issue(title="T", description="D", project_id=OTHER)

    def test_several_lists_and_no_choice_asks_instead_of_guessing(self) -> None:
        provider = FakeProvider()
        with pytest.raises(NeedsChoice) as excinfo:
            _guard(provider, scope=TWO_LISTS).create_issue(title="T", description="D")
        assert excinfo.value.payload["action"] == "choose-project"
        assert "create_issue" not in provider.names()


class TestUpdateIssue:
    def test_an_issue_in_scope_can_be_updated(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        _guard(provider).update_issue(issue_id="ABC-1", title="new")
        assert "update_issue" in provider.names()

    def test_an_issue_on_another_board_is_refused(self) -> None:
        """update-issue used to mutate any task id in the workspace."""
        provider = FakeProvider(owners={"XYZ-9": OTHER})
        with pytest.raises(ScopeViolation, match="outside this repo's scope"):
            _guard(provider).update_issue(issue_id="XYZ-9", title="new")
        assert "update_issue" not in provider.names()

    def test_ownership_costs_exactly_one_get(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        guard = _guard(provider)
        guard.update_issue(issue_id="ABC-1", title="a")
        guard.update_issue(issue_id="ABC-1", title="b")
        assert provider.names().count("get_issue") == 1

    def test_an_issue_with_no_project_is_refused(self) -> None:
        """Possible in Linear; no project means no scope can cover it."""
        provider = FakeProvider(owners={"ORPHAN-1": None})
        with pytest.raises(ScopeViolation, match="belongs to no project"):
            _guard(provider).update_issue(issue_id="ORPHAN-1", title="x")

    def test_nothing_to_change_is_refused_before_any_api_call(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        with pytest.raises(PMError, match="Nothing to update"):
            _guard(provider).update_issue(issue_id="ABC-1")
        assert provider.calls == []

    def test_state_and_assignee_are_resolved_from_names(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        _guard(provider).update_issue(
            issue_id="ABC-1", state="in progress", assignee_email="dev@x.io"
        )
        update = dict(provider.calls)["update_issue"]
        assert (update.state_id, update.assignee_id) == ("in progress", "42")

    def test_scope_is_checked_before_names_are_resolved(self) -> None:
        provider = FakeProvider(owners={"XYZ-9": OTHER})
        with pytest.raises(ScopeViolation):
            _guard(provider).update_issue(issue_id="XYZ-9", assignee_email="dev@x.io")
        assert "resolve_user_by_email" not in provider.names()


class FakeDocsProvider(FakeProvider):
    def create_doc(self, title: str, content: str | None) -> Doc:
        self.calls.append(("create_doc", (title, content)))
        return Doc(id="doc-1", title=title)

    def update_doc(
        self,
        doc_id: str,
        title: str | None = None,
        content: str | None = None,
        page_id: str | None = None,
    ) -> Doc:
        self.calls.append(("update_doc", doc_id))
        return Doc(id=doc_id, title=title or "")


class TestDocs:
    def test_a_provider_without_docs_is_refused(self) -> None:
        provider = FakeProvider()
        with pytest.raises(PMError, match="ClickUp only"):
            _guard(provider).create_doc(title="T", content=None)
        assert provider.calls == []

    def test_the_refusal_holds_in_dry_run_too(self) -> None:
        with pytest.raises(PMError, match="ClickUp only"):
            _guard(FakeProvider(), dry_run=True).update_doc(doc_id="d")

    def test_a_docs_provider_gets_the_call(self) -> None:
        provider = FakeDocsProvider()
        doc = _guard(provider).create_doc(title="T", content="body")
        assert isinstance(doc, Doc)
        assert dict(provider.calls)["create_doc"] == ("T", "body")

    def test_dry_run_does_not_reach_the_docs_api(self) -> None:
        provider = FakeDocsProvider()
        outcome = _guard(provider, dry_run=True).update_doc(doc_id="d", content="x")
        assert isinstance(outcome, DryRun)
        assert outcome.payload["has_content"] is True
        assert provider.calls == []


class TestDryRun:
    def test_nothing_reaches_the_api(self) -> None:
        provider = FakeProvider()
        outcome = _guard(provider, dry_run=True).create_issue(title="T", description="D")
        assert isinstance(outcome, DryRun)
        assert "create_issue" not in provider.names()

    def test_it_names_the_destination_a_human_recognises(self) -> None:
        outcome = _guard(FakeProvider(), dry_run=True).create_issue(title="T", description="D")
        assert outcome.destination == "Hemisphere → 4plus → modulo-energia"

    def test_it_still_refuses_out_of_scope_targets(self) -> None:
        """A preview of a forbidden write is still a forbidden write."""
        with pytest.raises(ScopeViolation):
            _guard(FakeProvider(), dry_run=True).create_issue(
                title="T", description="D", project_id=OTHER
            )

    def test_update_preview_carries_the_id(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        outcome = _guard(provider, dry_run=True).update_issue(issue_id="ABC-1", title="new")
        assert isinstance(outcome, DryRun)
        assert outcome.payload["id"] == "ABC-1"
        assert "update_issue" not in provider.names()

    def test_update_preview_shows_names_not_ids(self) -> None:
        provider = FakeProvider(owners={"ABC-1": IN_SCOPE})
        outcome = _guard(provider, dry_run=True).update_issue(
            issue_id="ABC-1", state="In Progress", assignee_email="dev@x.io"
        )
        assert isinstance(outcome, DryRun)
        assert (outcome.payload["state"], outcome.payload["assignee"]) == (
            "In Progress",
            "dev@x.io",
        )


class TestStructuralChanges:
    def test_creating_a_list_is_off_by_default(self) -> None:
        provider = FakeProvider()
        with pytest.raises(ScopeViolation, match="--allow-structural-changes"):
            _guard(provider).create_project("new-list")
        assert "create_project" not in provider.names()

    def test_creating_a_space_is_off_by_default(self) -> None:
        with pytest.raises(ScopeViolation, match="--allow-structural-changes"):
            _guard(FakeProvider()).create_team("new-space")

    def test_the_flag_enables_it(self) -> None:
        provider = FakeProvider()
        _guard(provider, allow_structural_changes=True).create_project("new-list")
        assert dict(provider.calls)["create_project"] == ("new-list", "space-1")

    def test_it_lands_in_this_repos_space(self) -> None:
        provider = FakeProvider()
        _guard(provider, allow_structural_changes=True).create_project("x")
        assert dict(provider.calls)["create_project"][1] == SCOPE.team_id


class TestDefaults:
    def test_repo_labels_apply_without_anyone_passing_them(self) -> None:
        """Two repos sharing one list stay distinguishable on their own."""
        provider = FakeProvider()
        guard = _guard(provider, defaults=IssueDefaults(labels=("alerts-api",)))
        guard.create_issue(title="T", description="D")
        assert dict(provider.calls)["create_issue"].label_ids == ("alerts-api",)

    def test_explicit_labels_come_after_the_defaults(self) -> None:
        guard = _guard(FakeProvider(), defaults=IssueDefaults(labels=("alerts-api",)))
        assert guard.merge_labels(["bug"]) == ("alerts-api", "bug")

    def test_duplicates_are_dropped_case_insensitively(self) -> None:
        guard = _guard(FakeProvider(), defaults=IssueDefaults(labels=("Alerts-API",)))
        assert guard.merge_labels(["alerts-api", "bug"]) == ("Alerts-API", "bug")

    def test_default_state_and_priority_are_applied(self) -> None:
        provider = FakeProvider()
        guard = _guard(provider, defaults=IssueDefaults(state="Backlog", priority=3))
        guard.create_issue(title="T", description="D")
        draft = dict(provider.calls)["create_issue"]
        assert draft.state_id == "Backlog"
        assert draft.priority == 3

    def test_explicit_values_win_over_defaults(self) -> None:
        provider = FakeProvider()
        guard = _guard(provider, defaults=IssueDefaults(state="Backlog", priority=3))
        guard.create_issue(title="T", description="D", state="In Progress", priority=1)
        draft = dict(provider.calls)["create_issue"]
        assert draft.state_id == "in progress"
        assert draft.priority == 1


class TestResolution:
    def test_unknown_state_lists_the_known_ones(self) -> None:
        with pytest.raises(PMError, match="Backlog"):
            _guard(FakeProvider()).create_issue(title="T", description="D", state="Nope")

    def test_state_matching_ignores_case(self) -> None:
        provider = FakeProvider()
        _guard(provider).create_issue(title="T", description="D", state="in progress")
        assert dict(provider.calls)["create_issue"].state_id == "in progress"

    def test_unknown_assignee_is_reported(self) -> None:
        with pytest.raises(PMError, match="No member with email"):
            _guard(FakeProvider()).create_issue(
                title="T", description="D", assignee_email="ghost@example.com"
            )

    def test_no_state_and_no_labels_cost_no_lookup(self) -> None:
        provider = FakeProvider()
        _guard(provider).create_issue(title="T", description="D")
        assert "list_states" not in provider.names()
        assert "list_labels" not in provider.names()

    def test_an_unknown_state_is_refused_before_writing(self) -> None:
        provider = FakeProvider()
        with pytest.raises(PMError, match="not found"):
            _guard(provider).create_issue(title="T", description="D", state="Nope")
        assert "create_issue" not in provider.names()

    def test_an_unknown_label_is_refused_before_writing(self) -> None:
        provider = FakeProvider()
        with pytest.raises(PMError, match="does not exist in this space"):
            _guard(provider).create_issue(title="T", description="D", labels=["nope"])
        assert "create_issue" not in provider.names()


class TestBuildGuard:
    """The workspace pin, checked once before any write is possible."""

    def _config(self, *, workspace_id: str = "ws-1") -> RepoContext:
        pm_file = RepoBinding(
            path=Path("/repo/.pm.toml"),
            repo_root=Path("/repo"),
            provider_type=ProviderType.CLICKUP,
            profile_name="4plus",
            scope=WriteScope(
                workspace_id=workspace_id,
                team_id="space-1",
                projects=(ScopeProject(id=IN_SCOPE, name="modulo-energia"),),
            ),
        )
        return RepoContext(
            pm_file=pm_file,
            profile=CredentialProfile("4plus", ProviderType.CLICKUP, "pk_x", workspace_id),
        )

    def test_a_reachable_workspace_yields_a_guard(self) -> None:
        guard = build_guard(self._config(), FakeProvider(reachable=("ws-1",)))
        assert guard.scope.workspace_id == "ws-1"

    def test_an_unreachable_workspace_is_refused(self) -> None:
        """Wrong profile, or a rotated token — caught before anything is written."""
        with pytest.raises(ScopeViolation, match="cannot reach workspace"):
            build_guard(self._config(), FakeProvider(reachable=("ws-other",)))

    def test_the_refusal_says_what_the_token_does_reach(self) -> None:
        with pytest.raises(ScopeViolation, match="ws-other"):
            build_guard(self._config(), FakeProvider(reachable=("ws-other",)))

    def test_repo_defaults_are_carried_into_the_guard(self) -> None:
        guard = build_guard(self._config(), FakeProvider(), dry_run=True)
        assert guard.dry_run is True
        assert guard.allow_structural_changes is False

    def test_the_pin_can_be_skipped_when_already_checked(self) -> None:
        """prepare_write verifies it earlier, so the guard must not pay for it twice."""
        provider = FakeProvider(reachable=("ws-other",))
        guard = build_guard(self._config(), provider, check_workspace_pin=False)
        assert "reachable_workspace_ids" not in provider.names()
        assert guard.scope.workspace_id == "ws-1"

    def test_verify_workspace_pin_is_callable_on_its_own(self) -> None:
        with pytest.raises(ScopeViolation, match="cannot reach workspace"):
            verify_workspace_pin(self._config(), FakeProvider(reachable=("ws-other",)))
