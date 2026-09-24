"""The setup chain: what the tool tells you to do next, and in what order."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.claude_pm.application import onboarding
from src.claude_pm.application.onboarding import READY, Step, next_step

CREDENTIALS = """
version = 1

[profiles.solo]
provider = "clickup"
token    = "pk_cccccccccccc"
"""

TWO_PROVIDERS = """
version = 1

[profiles.clicky]
provider = "clickup"
token    = "pk_aaaaaaaaaaaa"

[profiles.liny]
provider = "linear"
token    = "lin_api_bbbbbbbb"
"""


@pytest.fixture
def stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Drive each precondition independently, without touching the real machine."""
    skill = tmp_path / "skills" / "pm" / "SKILL.md"
    creds = tmp_path / "credentials.toml"
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    monkeypatch.setattr(onboarding, "SKILL_FILE", skill)
    monkeypatch.setenv("PM_CREDENTIALS_FILE", str(creds))

    class Stage:
        def __init__(self) -> None:
            self.repo = repo
            self.outside = tmp_path / "loose"
            self.outside.mkdir()

        def install_skill(self) -> None:
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text("---\nname: pm\n---\n", encoding="utf-8")

        def add_permissions(self) -> None:
            monkeypatch.setattr(
                "src.claude_pm.infrastructure.permissions.missing_permissions", lambda: []
            )

        def break_permissions(self) -> None:
            monkeypatch.setattr(
                "src.claude_pm.infrastructure.permissions.missing_permissions",
                lambda: ["Bash(pm:*)"],
            )

        def add_credentials(self) -> None:
            creds.write_text(CREDENTIALS, encoding="utf-8")

        def add_two_provider_credentials(self) -> None:
            creds.write_text(TWO_PROVIDERS, encoding="utf-8")

        def break_credentials(self) -> None:
            creds.write_text("this is not toml {{{", encoding="utf-8")

        def bind_repo(self) -> None:
            (repo / ".pm.toml").write_text("x", encoding="utf-8")

    return Stage()


class TestChainOrder:
    def test_nothing_installed_points_at_install_skill(self, stage) -> None:
        assert next_step(stage.repo).command == "pm install-skill --yes"

    def test_skill_without_permissions_still_points_there(self, stage) -> None:
        stage.install_skill()
        stage.break_permissions()
        assert next_step(stage.repo).command == "pm install-skill --yes"

    def test_then_credentials(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        assert next_step(stage.repo).command.startswith("pm creds add")

    def test_then_the_repo_binding(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.add_credentials()
        assert next_step(stage.repo).command == "pm init"

    def test_everything_done_is_ready(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.add_credentials()
        stage.bind_repo()
        assert next_step(stage.repo) == READY

    def test_the_chain_never_skips_ahead(self, stage) -> None:
        """A bound repo with no token must still ask for the token."""
        stage.install_skill()
        stage.add_permissions()
        stage.bind_repo()
        assert next_step(stage.repo).command.startswith("pm creds add")


class TestEdgeCases:
    def test_unreadable_credentials_are_reported_not_ignored(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.break_credentials()
        assert next_step(stage.repo).command == "pm creds list"

    def test_outside_a_git_repo_it_says_so(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.add_credentials()
        step = next_step(stage.outside)
        assert "git repo" in step.why
        assert step.command.startswith("cd ")

    def test_the_token_step_says_where_to_get_one(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        assert "Settings → Apps" in next_step(stage.repo).hint


class TestRender:
    def test_shows_the_command_on_its_own_line(self) -> None:
        rendered = Step(why="do something", command="pm something").render()
        assert "▸ Next step: do something" in rendered
        assert "      pm something" in rendered

    def test_multi_line_hints_stay_indented(self) -> None:
        rendered = Step(why="w", command="c", hint="uno\ndos").render()
        assert "    uno" in rendered
        assert "    dos" in rendered

    def test_no_hint_adds_no_blank_lines(self) -> None:
        assert Step(why="w", command="c").render().count("\n") == 2


class TestProviderAmbiguity:
    """The suggested command has to be one that actually runs."""

    def test_one_provider_needs_no_flag(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.add_credentials()
        assert next_step(stage.repo).command == "pm init"

    def test_two_providers_suggest_naming_a_profile(self, stage) -> None:
        stage.install_skill()
        stage.add_permissions()
        stage.add_two_provider_credentials()
        command = next_step(stage.repo).command
        assert command.startswith("pm init --profile")
        assert "clicky" in command and "liny" in command
