"""`pm creds add` — verification before storage, and the file it writes."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import pytest

from src.claude_pm.commands import creds
from src.claude_pm.exceptions import PMError, ProviderError
from src.claude_pm.models.tracker import Team
from src.claude_pm.repositories.credentials_repository import list_profiles
from src.claude_pm.repositories.toml import toml_string
from src.claude_pm.services import credential_service as profiles


class FakeProvider:
    def __init__(self, workspaces: list[Team] | None = None, broken: bool = False) -> None:
        self._workspaces = workspaces or [Team(id="ws-1", name="Hemisphere", key="H")]
        self._broken = broken

    def viewer_email(self) -> str:
        if self._broken:
            raise ProviderError("Authentication rejected (HTTP 401).")
        return "dev@example.com"

    def list_workspaces(self) -> list[Team]:
        return self._workspaces


@pytest.fixture
def creds_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "credentials.toml"
    monkeypatch.setenv("PM_CREDENTIALS_FILE", str(path))
    monkeypatch.delenv("PM_NEW_TOKEN", raising=False)
    return path


def _args(**overrides: object) -> argparse.Namespace:
    base = {
        "name": "4plus",
        "provider": "clickup",
        "token": "pk_valid_token",
        "workspace_id": None,
        "force": False,
        "dry_run": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _use(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(profiles, "create_provider", lambda *a, **k: provider)


class TestVerification:
    def test_a_bad_token_is_never_written(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing next to the paste that caused it beats failing three commands later."""
        _use(monkeypatch, FakeProvider(broken=True))
        with pytest.raises(PMError, match="does not work"):
            creds.add(_args())
        assert not creds_file.exists()

    def test_a_good_token_is_stored(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        profiles = list_profiles(creds_file)
        assert [p.name for p in profiles] == ["4plus"]
        assert profiles[0].token == "pk_valid_token"

    def test_dry_run_verifies_but_writes_nothing(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args(dry_run=True))
        assert not creds_file.exists()


class TestWorkspacePin:
    def test_a_single_workspace_is_adopted(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        assert list_profiles(creds_file)[0].workspace_id == "ws-1"

    def test_several_workspaces_leave_it_unpinned(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`pm init` asks which one; guessing here would repeat the old teams[0] bug."""
        _use(
            monkeypatch,
            FakeProvider([Team(id="a", name="A", key="A"), Team(id="b", name="B", key="B")]),
        )
        creds.add(_args())
        assert list_profiles(creds_file)[0].workspace_id is None

    def test_an_explicit_pin_is_honoured(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(
            monkeypatch,
            FakeProvider([Team(id="a", name="A", key="A"), Team(id="b", name="B", key="B")]),
        )
        creds.add(_args(workspace_id="b"))
        assert list_profiles(creds_file)[0].workspace_id == "b"

    def test_an_unreachable_pin_is_refused(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        with pytest.raises(PMError, match="cannot reach workspace"):
            creds.add(_args(workspace_id="nope"))
        assert not creds_file.exists()


class TestExistingProfiles:
    def test_a_duplicate_name_is_refused(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        with pytest.raises(PMError, match="already exists"):
            creds.add(_args(token="pk_other"))

    def test_force_replaces_rather_than_duplicates(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        creds.add(_args(token="pk_replacement", force=True))
        profiles = list_profiles(creds_file)
        assert [p.name for p in profiles] == ["4plus"]
        assert profiles[0].token == "pk_replacement"

    def test_a_second_profile_is_appended(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        creds.add(_args(name="interno", token="pk_second"))
        assert {p.name for p in list_profiles(creds_file)} == {"4plus", "interno"}

    def test_the_file_stays_valid_toml_with_one_version_key(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        creds.add(_args())
        creds.add(_args(name="interno", token="pk_second"))
        parsed = tomllib.loads(creds_file.read_text(encoding="utf-8"))
        assert parsed["version"] == 1
        assert set(parsed["profiles"]) == {"4plus", "interno"}


class TestTokenInput:
    def test_the_env_var_avoids_shell_history(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PM_NEW_TOKEN", "pk_from_env")
        _use(monkeypatch, FakeProvider())
        creds.add(_args(token=None))
        assert list_profiles(creds_file)[0].token == "pk_from_env"

    def test_no_token_anywhere_explains_both_ways(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        with pytest.raises(PMError, match="PM_NEW_TOKEN"):
            creds.add(_args(token=None))

    def test_an_unknown_provider_is_refused_before_any_call(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(PMError, match="Unknown provider"):
            creds.add(_args(provider="jira"))


class TestTomlEscaping:
    def test_a_token_with_quotes_and_backslashes_round_trips(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unescaped `"` or `\\` in the token used to corrupt the TOML it was written into."""
        tricky_token = 'pk_"weird"\\token'
        _use(monkeypatch, FakeProvider())
        creds.add(_args(token=tricky_token))
        profiles = list_profiles(creds_file)
        assert profiles[0].token == tricky_token

    def test_an_invalid_profile_name_is_rejected_before_anything_is_written(
        self, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, FakeProvider())
        with pytest.raises(PMError, match="letters, digits"):
            creds.add(_args(name='evil"] \n[profiles.other'))
        assert not creds_file.exists()


def test_control_characters_in_a_token_still_round_trip() -> None:
    """A token pasted with a stray newline or tab must not corrupt the file."""
    raw = 'pk_\n\t\x01"\\end\x7f'
    assert tomllib.loads(f"token = {toml_string(raw)}")["token"] == raw
