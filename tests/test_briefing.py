"""`pm briefing` output: SKILL.md reads both shapes, so they are locked here."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from src.claude_pm.commands import briefing
from src.claude_pm.enums import ProviderType
from src.claude_pm.models.repo_config import (
    CredentialProfile,
    RepoBinding,
    RepoConfig,
    ScopeProject,
    WriteScope,
)
from src.claude_pm.models.tracker import Issue, State


class FakeProvider:
    def list_open_issues(self, project_id: str) -> list[Issue]:
        return [
            Issue(identifier=f"{project_id}-1", title="a", state=State(id="s1", name="Backlog")),
            Issue(identifier=f"{project_id}-2", title="b", state=State(id="s2", name="Doing")),
        ]


def _run(projects: tuple[ScopeProject, ...], monkeypatch, capsys) -> dict:
    config = RepoConfig(
        pm_file=RepoBinding(
            path=Path("/repo/.pm.toml"),
            repo_root=Path("/repo"),
            provider_type=ProviderType.CLICKUP,
            profile_name="p",
            scope=WriteScope(workspace_id="ws", team_id="t", projects=projects),
        ),
        profile=CredentialProfile("p", ProviderType.CLICKUP, "pk_x"),
    )
    monkeypatch.setattr(briefing, "get_repo_config", lambda _args: config)
    monkeypatch.setattr(briefing, "get_provider", lambda _config: FakeProvider())
    briefing.run(argparse.Namespace(profile=None))
    return json.loads(capsys.readouterr().out)


def test_a_single_list_is_flat(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    output = _run((ScopeProject(id="l1", name="Main"),), monkeypatch, capsys)
    assert output["project"] == "Main"
    assert output["repo"] == "repo"
    assert output["total_open"] == 2
    assert [i["identifier"] for i in output["issues_by_state"]["Backlog"]] == ["l1-1"]


def test_several_lists_come_as_sections_in_pm_toml_order(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    output = _run(
        (ScopeProject(id="l2", name="Second"), ScopeProject(id="l1", name="First")),
        monkeypatch,
        capsys,
    )
    assert [p["project"] for p in output["projects"]] == ["Second", "First"]
    assert output["projects"][0]["project_id"] == "l2"
    assert output["projects"][0]["issues_by_state"]["Doing"][0]["identifier"] == "l2-2"
