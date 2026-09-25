"""Credential profile resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.claude_pm.enums import ProviderType
from src.claude_pm.exceptions import ConfigError
from src.claude_pm.models.repo_config import CredentialProfile
from src.claude_pm.repositories.credentials_repository import list_profiles
from src.claude_pm.services.credential_service import load_profile

TWO_PROFILES = """
version = 1

[profiles.4plus]
provider     = "clickup"
token        = "pk_aaaaaaaaaaaa"
workspace_id = "9013377000"

[profiles.personal-linear]
provider = "linear"
token    = "lin_api_bbbbbbbb"
"""

ONE_PROFILE = """
version = 1

[profiles.solo]
provider = "clickup"
token    = "pk_cccccccccccc"
"""


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PM_TOKEN", "PM_WORKSPACE_ID", "PM_CREDENTIALS_FILE"):
        monkeypatch.delenv(name, raising=False)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "credentials.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestListProfiles:
    def test_parses_all_profiles(self, tmp_path: Path) -> None:
        profiles = list_profiles(_write(tmp_path, TWO_PROFILES))
        assert [p.name for p in profiles] == ["4plus", "personal-linear"]
        assert profiles[0].provider_type is ProviderType.CLICKUP
        assert profiles[0].workspace_id == "9013377000"
        assert profiles[1].workspace_id is None

    def test_missing_file_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert list_profiles(tmp_path / "nope.toml") == []

    def test_rejects_unknown_key(self, tmp_path: Path) -> None:
        bad = ONE_PROFILE + "\n[profiles.other]\nprovider='linear'\ntoken='t'\nspace='x'\n"
        with pytest.raises(ConfigError, match="unknown key"):
            list_profiles(_write(tmp_path, bad))

    def test_rejects_empty_token(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="token is missing or empty"):
            list_profiles(_write(tmp_path, ONE_PROFILE.replace("pk_cccccccccccc", "")))

    def test_rejects_unknown_provider(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Unknown provider"):
            list_profiles(_write(tmp_path, ONE_PROFILE.replace("clickup", "jira")))


class TestLoadProfile:
    def test_by_name(self, tmp_path: Path) -> None:
        profile = load_profile(
            "personal-linear", provider=ProviderType.LINEAR, path=_write(tmp_path, TWO_PROFILES)
        )
        assert profile.provider_type is ProviderType.LINEAR

    def test_unknown_name_lists_what_exists(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Available: 4plus, personal-linear"):
            load_profile("typo", provider=ProviderType.CLICKUP, path=_write(tmp_path, TWO_PROFILES))

    def test_no_profiles_at_all(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="pm creds add"):
            load_profile("any", provider=ProviderType.CLICKUP, path=tmp_path / "absent.toml")


class TestEnvToken:
    def test_pm_token_bypasses_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PM_TOKEN", "pk_from_ci")
        monkeypatch.setenv("PM_WORKSPACE_ID", "999")
        profile = load_profile("ci", provider=ProviderType.CLICKUP, path=tmp_path / "absent.toml")
        assert profile.token == "pk_from_ci"
        assert profile.workspace_id == "999"

    def test_ambient_provider_keys_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stray CLICKUP_API_KEY must never become the token."""
        monkeypatch.setenv("CLICKUP_API_KEY", "pk_ambient")
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_ambient")
        with pytest.raises(ConfigError):
            load_profile("ci", provider=ProviderType.CLICKUP, path=Path("/nonexistent.toml"))


class TestRedaction:
    def test_keeps_only_the_tail(self) -> None:
        profile = CredentialProfile("p", ProviderType.CLICKUP, "pk_1234567890ab", "w")
        assert profile.redacted()["token"] == "…90ab"

    def test_short_token_shows_nothing(self) -> None:
        assert CredentialProfile("p", ProviderType.LINEAR, "short").redacted()["token"] == "…"
