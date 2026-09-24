"""`pm init`: resolving a board into a scope, and rendering it back as TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from src.claude_pm.enums import ProviderType
from src.claude_pm.exceptions import ConfigError, PMError
from src.claude_pm.models.repo_config import (
    CredentialProfile,
    IssueDefaults,
    ScopeProject,
    WriteScope,
)
from src.claude_pm.models.tracker import Project, Team
from src.claude_pm.repositories.pm_file_repository import parse_pm_file, render_pm_toml
from src.claude_pm.services.scope_discovery_service import (
    Option,
    choose_profile,
    discover_scope,
    verify_declared_scope,
)


class FakeProvider:
    def __init__(
        self,
        workspaces: list[Team] | None = None,
        spaces: list[Team] | None = None,
        projects: list[Project] | None = None,
    ) -> None:
        self._workspaces = workspaces or [Team(id="ws-1", name="Hemisphere", key="HEM")]
        self._spaces = spaces or [Team(id="space-1", name="4plus", key="4P")]
        self._projects = projects or [Project(id="list-1", name="modulo-energia")]

    def list_workspaces(self) -> list[Team]:
        return self._workspaces

    def list_teams(self) -> list[Team]:
        return self._spaces

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        return self._projects


class RecordingPick:
    """Answers every question with the options at `answers[flag]`, and remembers what was asked."""

    def __init__(self, answers: dict[str, list[str]] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[tuple[str, list[Option], bool]] = []

    def __call__(self, question: str, options, flag: str, multi: bool) -> list[str]:
        self.asked.append((flag, list(options), multi))
        return self.answers[flag]


def _discover(provider: FakeProvider, pick: RecordingPick, **flags):
    options = {"workspace_id": None, "team_id": None, "project_ids": None}
    options.update(flags)
    return discover_scope(lambda _ws: provider, pick=pick, **options)


TWO = [Team(id="a", name="A", key="A"), Team(id="b", name="B", key="B")]


class TestDiscoverScope:
    def test_single_options_are_adopted_without_asking(self) -> None:
        pick = RecordingPick()
        scope = _discover(FakeProvider(), pick)
        assert pick.asked == []
        assert scope.describe() == "Hemisphere → 4plus → modulo-energia"

    def test_several_workspaces_ask_with_the_flag_to_pass(self) -> None:
        pick = RecordingPick({"--workspace-id": ["b"]})
        scope = _discover(FakeProvider(workspaces=TWO), pick)
        assert scope.workspace_id == "b"
        assert pick.asked[0][0] == "--workspace-id"
        assert [o.id for o in pick.asked[0][1]] == ["a", "b"]

    def test_several_spaces_ask(self) -> None:
        pick = RecordingPick({"--space-id": ["a"]})
        assert _discover(FakeProvider(spaces=TWO), pick).team_id == "a"

    def test_several_lists_are_a_multi_choice(self) -> None:
        lists = [Project(id="l1", name="One"), Project(id="l2", name="Two")]
        pick = RecordingPick({"--list-id": ["l1", "l2"]})
        scope = _discover(FakeProvider(projects=lists), pick)
        assert scope.project_ids == {"l1", "l2"}
        assert pick.asked[0][2] is True

    def test_flags_win_and_skip_the_question(self) -> None:
        pick = RecordingPick()
        scope = _discover(
            FakeProvider(workspaces=TWO, spaces=TWO), pick, workspace_id="a", team_id="b"
        )
        assert (scope.workspace_id, scope.team_id) == ("a", "b")
        assert pick.asked == []

    def test_an_unknown_id_lists_what_exists(self) -> None:
        with pytest.raises(PMError, match="modulo-energia"):
            _discover(FakeProvider(), RecordingPick(), project_ids=["ghost"])

    def test_the_provider_is_pinned_once_the_workspace_is_known(self) -> None:
        """Spaces cannot be listed before the workspace is decided."""
        pins: list[str | None] = []

        def make_provider(workspace_id: str | None) -> FakeProvider:
            pins.append(workspace_id)
            return FakeProvider()

        discover_scope(
            make_provider, workspace_id=None, team_id=None, project_ids=None, pick=RecordingPick()
        )
        assert pins == [None, "ws-1"]


CLICKUP = CredentialProfile("4plus", ProviderType.CLICKUP, "pk_secret_token")
OTHER_CLICKUP = CredentialProfile("otro", ProviderType.CLICKUP, "pk_other_token")
LINEAR = CredentialProfile("personal", ProviderType.LINEAR, "lin_api_token")


class TestChooseProfile:
    def test_no_profiles_says_how_to_add_one(self) -> None:
        with pytest.raises(ConfigError, match="pm creds add"):
            choose_profile([], name=None, provider=None, pick=RecordingPick())

    def test_a_named_profile_wins(self) -> None:
        chosen = choose_profile(
            [CLICKUP, LINEAR], name="personal", provider=None, pick=RecordingPick()
        )
        assert chosen is LINEAR

    def test_an_unknown_name_lists_what_exists(self) -> None:
        with pytest.raises(PMError, match="Available: 4plus, personal"):
            choose_profile([CLICKUP, LINEAR], name="typo", provider=None, pick=RecordingPick())

    def test_a_named_profile_must_match_the_provider(self) -> None:
        with pytest.raises(PMError, match="is for clickup"):
            choose_profile(
                [CLICKUP], name="4plus", provider=ProviderType.LINEAR, pick=RecordingPick()
            )

    def test_the_only_profile_for_the_provider_is_adopted(self) -> None:
        pick = RecordingPick()
        chosen = choose_profile(
            [CLICKUP, LINEAR], name=None, provider=ProviderType.LINEAR, pick=pick
        )
        assert chosen is LINEAR
        assert pick.asked == []

    def test_several_candidates_ask_and_never_show_a_token(self) -> None:
        pick = RecordingPick({"--profile": ["otro"]})
        chosen = choose_profile([CLICKUP, OTHER_CLICKUP], name=None, provider=None, pick=pick)
        assert chosen is OTHER_CLICKUP
        assert "pk_" not in repr(pick.asked)


class TestRenderPmToml:
    def _scope(self) -> WriteScope:
        return WriteScope(
            workspace_id="ws-1",
            workspace_name="Hemisphere",
            team_id="space-1",
            team_name="4plus",
            projects=(ScopeProject(id="list-1", name="modulo-energia"),),
        )

    def test_what_it_writes_parses_back_identically(self) -> None:
        rendered = render_pm_toml(
            provider_name="clickup",
            profile_name="4plus",
            scope=self._scope(),
            defaults=IssueDefaults(labels=("alerts-api",), state="Backlog", priority=3),
        )
        parsed = parse_pm_file(rendered, path=Path("/repo/.pm.toml"))
        assert parsed.provider_type.value == "clickup"
        assert parsed.profile_name == "4plus"
        assert parsed.scope == self._scope()
        assert parsed.defaults == IssueDefaults(labels=("alerts-api",), state="Backlog", priority=3)

    def test_it_is_valid_toml(self) -> None:
        rendered = render_pm_toml(provider_name="linear", profile_name="p", scope=self._scope())
        assert tomllib.loads(rendered)["provider"] == "linear"

    def test_the_defaults_table_is_omitted_when_empty(self) -> None:
        rendered = render_pm_toml(provider_name="linear", profile_name="p", scope=self._scope())
        assert "[defaults]" not in rendered

    def test_quotes_in_names_are_escaped(self) -> None:
        scope = WriteScope(
            workspace_id="ws",
            team_id="sp",
            team_name='the "main" space',
            projects=(ScopeProject(id="l", name="a\\b"),),
        )
        rendered = render_pm_toml(provider_name="linear", profile_name="p", scope=scope)
        assert tomllib.loads(rendered)["scope"]["space_name"] == 'the "main" space'
        assert tomllib.loads(rendered)["scope"]["lists"][0]["name"] == "a\\b"

    def test_several_lists_round_trip(self) -> None:
        scope = WriteScope(
            workspace_id="ws",
            team_id="sp",
            projects=(ScopeProject(id="a", name="A"), ScopeProject(id="b", name="B")),
        )
        rendered = render_pm_toml(provider_name="clickup", profile_name="p", scope=scope)
        assert parse_pm_file(rendered, path=Path("/x/.pm.toml")).scope.project_ids == {"a", "b"}


class TestVerifyDeclaredScope:
    SOURCE = Path("/repo/.pm.toml")

    def _scope(self, **overrides) -> WriteScope:
        fields = {
            "workspace_id": "ws-1",
            "team_id": "space-1",
            "team_name": "4plus",
            "projects": (ScopeProject(id="list-1", name="modulo-energia"),),
        }
        fields.update(overrides)
        return WriteScope(**fields)

    def test_an_intact_board_has_no_warnings(self) -> None:
        assert verify_declared_scope(FakeProvider(), self._scope(), self.SOURCE) == []

    def test_a_missing_space_is_refused(self) -> None:
        with pytest.raises(PMError, match="does not exist"):
            verify_declared_scope(FakeProvider(), self._scope(team_id="ghost"), self.SOURCE)

    def test_a_missing_list_names_what_exists(self) -> None:
        scope = self._scope(projects=(ScopeProject(id="ghost", name="x"),))
        with pytest.raises(PMError, match="modulo-energia"):
            verify_declared_scope(FakeProvider(), scope, self.SOURCE)

    def test_a_renamed_list_is_a_warning(self) -> None:
        scope = self._scope(projects=(ScopeProject(id="list-1", name="old-name"),))
        [warning] = verify_declared_scope(FakeProvider(), scope, self.SOURCE)
        assert "now named 'modulo-energia'" in warning
