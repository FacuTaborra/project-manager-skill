"""CLI wiring: which commands accept which safety flags, and how they parse."""

from __future__ import annotations

import argparse

import pytest

from src.claude_pm import cli
from src.claude_pm.cli import build_parser
from src.claude_pm.exceptions import EXIT_ERROR

WRITE_COMMANDS = [
    ["create-issue", "--title", "T", "--description", "D"],
    ["update-issue", "--id", "ABC-1", "--title", "T"],
    ["create-doc", "--title", "T"],
    ["update-doc", "--doc-id", "D1"],
]

STRUCTURAL_COMMANDS = [
    ["create-project", "some-name"],
    ["create-team", "some-name"],
]

READ_COMMANDS = [
    ["briefing"],
    ["search", "q"],
    ["get-issue", "--id", "ABC-1"],
    ["list-teams"],
    ["list-projects"],
    ["list-states"],
    ["list-labels"],
    ["resolve-user", "a@b.com"],
]


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


class TestDryRun:
    @pytest.mark.parametrize("argv", WRITE_COMMANDS + STRUCTURAL_COMMANDS)
    def test_every_mutating_command_accepts_it(self, argv: list[str]) -> None:
        assert _parse([*argv, "--dry-run"]).dry_run is True

    @pytest.mark.parametrize("argv", WRITE_COMMANDS + STRUCTURAL_COMMANDS)
    def test_it_defaults_to_off(self, argv: list[str]) -> None:
        assert _parse(argv).dry_run is False

    @pytest.mark.parametrize("argv", READ_COMMANDS)
    def test_reads_do_not_offer_it(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit):
            _parse([*argv, "--dry-run"])

    def test_it_belongs_to_the_subcommand_not_the_root(self) -> None:
        """On the root parser the subparser's default would silently overwrite it."""
        with pytest.raises(SystemExit):
            _parse(["--dry-run", "briefing"])


class TestStructuralFlag:
    @pytest.mark.parametrize("argv", STRUCTURAL_COMMANDS)
    def test_structural_commands_accept_it(self, argv: list[str]) -> None:
        assert _parse([*argv, "--allow-structural-changes"]).allow_structural_changes is True

    @pytest.mark.parametrize("argv", STRUCTURAL_COMMANDS)
    def test_it_defaults_to_off(self, argv: list[str]) -> None:
        assert _parse(argv).allow_structural_changes is False

    @pytest.mark.parametrize("argv", WRITE_COMMANDS)
    def test_ordinary_writes_cannot_ask_for_it(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit):
            _parse([*argv, "--allow-structural-changes"])

    def test_create_project_no_longer_takes_a_team_id(self) -> None:
        """The destination space comes from .pm.toml, not from the caller."""
        with pytest.raises(SystemExit):
            _parse(["create-project", "x", "--team-id", "anything"])


class TestCommonFlags:
    @pytest.mark.parametrize("argv", WRITE_COMMANDS + READ_COMMANDS)
    def test_profile_override_is_available_everywhere(self, argv: list[str]) -> None:
        assert _parse([*argv, "--profile", "4plus"]).profile == "4plus"


class TestInit:
    def test_from_legacy_is_gone(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["init", "--from-legacy"])

    def test_list_id_is_repeatable(self) -> None:
        assert _parse(["init", "--list-id", "a", "--list-id", "b"]).list_id == ["a", "b"]

    def test_it_defaults_to_not_overwriting(self) -> None:
        assert _parse(["init"]).force is False


class TestNoInput:
    """The escape hatch that forces the machine protocol regardless of the terminal."""

    def test_init_accepts_it(self) -> None:
        assert _parse(["init", "--no-input"]).no_input is True

    def test_creds_add_accepts_it(self) -> None:
        assert _parse(["creds", "add", "--no-input"]).no_input is True

    def test_it_defaults_to_off(self) -> None:
        assert _parse(["init"]).no_input is False
        assert _parse(["creds", "add"]).no_input is False


class TestInstallSkill:
    def test_permission_consent_is_explicit(self) -> None:
        assert _parse(["install-skill"]).yes is False
        assert _parse(["install-skill", "--yes"]).yes is True

    def test_skill_only_install_is_possible(self) -> None:
        assert _parse(["install-skill", "--skip-permissions"]).skip_permissions is True


class TestCreds:
    def test_creds_import_is_gone(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["creds", "import"])

    def test_the_two_subcommands_exist(self) -> None:
        assert _parse(["creds", "list"]).creds_cmd == "list"
        assert (
            _parse(
                ["creds", "add", "--name", "n", "--provider", "clickup", "--token", "t"]
            ).creds_cmd
            == "add"
        )

    def test_a_subcommand_is_required(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["creds"])

    def test_add_no_longer_demands_name_and_provider_up_front(self) -> None:
        """They are prompted for in a terminal; --no-input turns them back into errors."""
        args = _parse(["creds", "add", "--token", "t"])
        assert args.name is None
        assert args.provider is None

    def test_add_allows_omitting_the_token_for_the_env_var(self) -> None:
        assert _parse(["creds", "add", "--name", "n", "--provider", "clickup"]).token is None

    def test_add_takes_a_workspace_pin_and_force(self) -> None:
        args = _parse(
            [
                "creds",
                "add",
                "--name",
                "n",
                "--provider",
                "clickup",
                "--token",
                "t",
                "--workspace-id",
                "w",
                "--force",
            ]
        )
        assert args.workspace_id == "w"
        assert args.force is True


class TestOSErrorHandling:
    """An unhandled OSError (e.g. a permissions or disk problem) must not print a traceback."""

    def test_it_prints_a_one_line_message_and_returns_exit_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(args: object) -> int:
            raise OSError(13, "Permission denied", "/no/such/path")

        class FakeParser:
            def parse_args(self, argv: list[str] | None = None) -> object:
                return argparse.Namespace(func=boom)

        monkeypatch.setattr(cli, "build_parser", lambda: FakeParser())

        exit_code = cli.main([])

        captured = capsys.readouterr()
        assert exit_code == EXIT_ERROR
        assert "Permission denied" in captured.err
        assert "/no/such/path" in captured.err


class TestRemovedSurface:
    def test_setup_can_no_longer_create_a_project(self) -> None:
        """Discovery is gone: the board comes from .pm.toml."""
        with pytest.raises(SystemExit):
            _parse(["setup", "--create-project"])

    def test_setup_no_longer_takes_id_overrides(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["setup", "--team-id", "x"])
