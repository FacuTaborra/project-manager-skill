"""`pm init` asks a person and tells everyone else which flag to pass."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from src.claude_pm.commands import _input, init
from src.claude_pm.enums import ProviderType
from src.claude_pm.exceptions import EXIT_ERROR, PMError
from src.claude_pm.models.repo_config import CredentialProfile
from src.claude_pm.models.tracker import Project, Team

PROFILE = CredentialProfile("urbs", ProviderType.CLICKUP, "pk_secret")


class FakeProvider:
    def list_workspaces(self) -> list[Team]:
        return [Team(id="w1", name="One", key="w1"), Team(id="w2", name="Two", key="w2")]

    def list_teams(self) -> list[Team]:
        return [Team(id="s1", name="Space", key="s1")]

    def list_projects(self, team_id: str | None = None) -> list[Project]:
        return [Project(id="l1", name="List")]


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "profile": None,
        "provider": None,
        "workspace_id": None,
        "space_id": None,
        "list_id": None,
        "force": False,
        "dry_run": False,
        "no_input": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(init, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(init, "list_profiles", lambda: [PROFILE])
    monkeypatch.setattr(init, "create_provider", lambda *_a, **_kw: FakeProvider())
    monkeypatch.setattr(init, "next_step", lambda _root: type("S", (), {"render": lambda s: ""})())
    return tmp_path


class TestWithoutAPerson:
    def test_no_input_never_prompts_even_on_a_tty(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_input, "is_interactive", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted despite --no-input"))
        with pytest.raises(PMError) as excinfo:
            init.run(_args(no_input=True))
        assert excinfo.value.exit_code == EXIT_ERROR
        assert "--workspace-id" in str(excinfo.value)

    def test_the_error_lists_every_option(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_input, "is_interactive", lambda: False)
        with pytest.raises(PMError, match="w1") as excinfo:
            init.run(_args())
        assert "w2" in str(excinfo.value)

    def test_the_flag_answers_it(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_input, "is_interactive", lambda: False)
        assert init.run(_args(workspace_id="w2")) == 0
        assert 'workspace_id   = "w2"' in (repo / ".pm.toml").read_text(encoding="utf-8")


class TestWithAPerson:
    def test_the_menu_answer_lands_in_pm_toml(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_input, "is_interactive", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "2")
        assert init.run(_args()) == 0
        assert 'workspace_id   = "w2"' in (repo / ".pm.toml").read_text(encoding="utf-8")


class TestFirstCredential:
    def test_the_wizard_asks_for_a_token_when_there_is_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sending someone to another command mid-flow is the friction we removed."""
        saved: dict[str, object] = {}
        profiles: list[CredentialProfile] = []

        monkeypatch.setattr(_input, "is_interactive", lambda: True)
        monkeypatch.setattr(init, "list_profiles", lambda: profiles)
        monkeypatch.setattr(
            init,
            "credential_fields",
            lambda *_a, **_kw: (ProviderType.CLICKUP, "pk_typed_by_hand", "urbs"),
        )
        monkeypatch.setattr(
            init, "probe_token", lambda p, t: ("dev@example.com", [Team("w1", "One", "w1")])
        )
        monkeypatch.setattr(init, "print_profile_saved", lambda *a: None)

        def save_profile(name, provider, token, ws, **_kw) -> None:  # type: ignore[no-untyped-def]
            saved.update(name=name, token=token, ws=ws)
            profiles.append(CredentialProfile(name, provider, token, ws))

        monkeypatch.setattr(init, "save_profile", save_profile)

        args = _args(workspace_id="w1")
        assert init.run(args) == 0
        assert saved == {"name": "urbs", "token": "pk_typed_by_hand", "ws": "w1"}
        assert args.profile == "urbs"
