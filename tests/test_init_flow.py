"""`pm init`: resolving a board into a scope, and rendering it back as TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from src.claude_pm.application.init_flow import (
    build_scope,
    defaults_from_legacy,
    read_legacy_section,
    resolve_lists,
    resolve_space,
    resolve_workspace,
)
from src.claude_pm.domain.models import Project, Team
from src.claude_pm.exceptions import NeedsChoice, PMError
from src.claude_pm.pmfile import Defaults, ListRef, ScopeSpec, parse_pm_file
from src.claude_pm.pmfile_render import render_pm_toml

LEGACY = """\
# Mapeo de repos a proyectos en el tracker.

[alerts-api]
provider: clickup
space: 4plus
project: modulo-energia
label: alerts-api

[cahpsa-etl]
provider: clickup
space: Cahpsa
project: Melvin, Nutrex, Witwot
"""


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


class TestLegacyFile:
    def test_reads_a_section_case_insensitively(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.pm"
        path.write_text(LEGACY, encoding="utf-8")
        section = read_legacy_section(path, "Alerts-API")
        assert section is not None
        assert section.space == "4plus"
        assert section.projects == ("modulo-energia",)
        assert section.label == "alerts-api"

    def test_comma_separated_projects_become_a_tuple(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.pm"
        path.write_text(LEGACY, encoding="utf-8")
        section = read_legacy_section(path, "cahpsa-etl")
        assert section is not None
        assert section.projects == ("Melvin", "Nutrex", "Witwot")

    def test_unknown_repo_is_none(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.pm"
        path.write_text(LEGACY, encoding="utf-8")
        assert read_legacy_section(path, "not-here") is None

    def test_absent_file_is_none(self, tmp_path: Path) -> None:
        assert read_legacy_section(tmp_path / "nope.pm", "x") is None

    def test_the_dead_label_becomes_a_default(self, tmp_path: Path) -> None:
        """`label:` was parsed and dropped. This is where it finally does something."""
        path = tmp_path / "projects.pm"
        path.write_text(LEGACY, encoding="utf-8")
        section = read_legacy_section(path, "alerts-api")
        assert defaults_from_legacy(section) == Defaults(labels=("alerts-api",))

    def test_no_label_means_no_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.pm"
        path.write_text(LEGACY, encoding="utf-8")
        assert defaults_from_legacy(read_legacy_section(path, "cahpsa-etl")) == Defaults()


class TestResolution:
    def test_a_single_workspace_is_adopted(self) -> None:
        assert resolve_workspace(FakeProvider(), None) == ("ws-1", "Hemisphere")

    def test_several_workspaces_ask(self) -> None:
        provider = FakeProvider(
            workspaces=[Team(id="a", name="A", key="A"), Team(id="b", name="B", key="B")]
        )
        with pytest.raises(NeedsChoice) as excinfo:
            resolve_workspace(provider, None)
        assert excinfo.value.payload["action"] == "choose-workspace"

    def test_a_declared_workspace_must_be_reachable(self) -> None:
        with pytest.raises(PMError, match="cannot reach workspace"):
            resolve_workspace(FakeProvider(), "ws-other")

    def test_space_by_legacy_name(self) -> None:
        assert resolve_space(FakeProvider(), space_id=None, space_name="4plus") == (
            "space-1",
            "4plus",
        )

    def test_space_by_name_is_case_insensitive(self) -> None:
        assert resolve_space(FakeProvider(), space_id=None, space_name="4PLUS")[0] == "space-1"

    def test_unknown_space_name_lists_the_options(self) -> None:
        with pytest.raises(PMError, match="4plus"):
            resolve_space(FakeProvider(), space_id=None, space_name="ghost")

    def test_several_spaces_and_no_hint_asks(self) -> None:
        provider = FakeProvider(
            spaces=[Team(id="a", name="A", key="A"), Team(id="b", name="B", key="B")]
        )
        with pytest.raises(NeedsChoice) as excinfo:
            resolve_space(provider, space_id=None, space_name=None)
        assert excinfo.value.payload["action"] == "choose-space"

    def test_lists_by_legacy_names(self) -> None:
        refs = resolve_lists(FakeProvider(), "space-1", list_names=["modulo-energia"])
        assert refs == (ListRef(id="list-1", name="modulo-energia"),)

    def test_lists_by_id(self) -> None:
        refs = resolve_lists(FakeProvider(), "space-1", list_ids=["list-1"])
        assert refs == (ListRef(id="list-1", name="modulo-energia"),)

    def test_unknown_list_id_is_refused(self) -> None:
        with pytest.raises(PMError, match="not found in this space"):
            resolve_lists(FakeProvider(), "space-1", list_ids=["ghost"])

    def test_no_hint_asks_rather_than_picking(self) -> None:
        with pytest.raises(NeedsChoice) as excinfo:
            resolve_lists(FakeProvider(), "space-1")
        assert excinfo.value.payload["action"] == "choose-list"


class TestBuildScope:
    def test_end_to_end_from_legacy_names(self) -> None:
        scope = build_scope(
            lambda _workspace_id: FakeProvider(),
            workspace_id=None,
            space_name="4plus",
            list_names=["modulo-energia"],
        )
        assert scope.workspace_id == "ws-1"
        assert scope.space_id == "space-1"
        assert scope.list_ids == {"list-1"}
        assert scope.describe() == "Hemisphere → 4plus → modulo-energia"

    def test_the_provider_is_pinned_once_the_workspace_is_known(self) -> None:
        """Spaces cannot be listed before the workspace is decided."""
        pins: list[str | None] = []

        def make_provider(workspace_id: str | None) -> FakeProvider:
            pins.append(workspace_id)
            return FakeProvider()

        build_scope(
            make_provider, workspace_id=None, space_name="4plus", list_names=["modulo-energia"]
        )
        assert pins == [None, "ws-1"]


class TestRenderPmToml:
    def _scope(self) -> ScopeSpec:
        return ScopeSpec(
            workspace_id="ws-1",
            workspace_name="Hemisphere",
            space_id="space-1",
            space_name="4plus",
            lists=(ListRef(id="list-1", name="modulo-energia"),),
        )

    def test_what_it_writes_parses_back_identically(self) -> None:
        rendered = render_pm_toml(
            provider="clickup",
            profile="4plus",
            scope=self._scope(),
            defaults=Defaults(labels=("alerts-api",), state="Backlog", priority=3),
        )
        parsed = parse_pm_file(rendered, path=Path("/repo/.pm.toml"))
        assert parsed.provider.value == "clickup"
        assert parsed.profile == "4plus"
        assert parsed.scope == self._scope()
        assert parsed.defaults == Defaults(labels=("alerts-api",), state="Backlog", priority=3)

    def test_it_is_valid_toml(self) -> None:
        rendered = render_pm_toml(provider="linear", profile="p", scope=self._scope())
        assert tomllib.loads(rendered)["provider"] == "linear"

    def test_the_defaults_table_is_omitted_when_empty(self) -> None:
        rendered = render_pm_toml(provider="linear", profile="p", scope=self._scope())
        assert "[defaults]" not in rendered

    def test_quotes_in_names_are_escaped(self) -> None:
        scope = ScopeSpec(
            workspace_id="ws",
            space_id="sp",
            space_name='the "main" space',
            lists=(ListRef(id="l", name="a\\b"),),
        )
        rendered = render_pm_toml(provider="linear", profile="p", scope=scope)
        assert tomllib.loads(rendered)["scope"]["space_name"] == 'the "main" space'
        assert tomllib.loads(rendered)["scope"]["lists"][0]["name"] == "a\\b"

    def test_several_lists_round_trip(self) -> None:
        scope = ScopeSpec(
            workspace_id="ws",
            space_id="sp",
            lists=(ListRef(id="a", name="A"), ListRef(id="b", name="B")),
        )
        rendered = render_pm_toml(provider="clickup", profile="p", scope=scope)
        assert parse_pm_file(rendered, path=Path("/x/.pm.toml")).scope.list_ids == {"a", "b"}
