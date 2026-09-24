"""Registering Claude Code permissions — the one write outside repo and tracker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.claude_pm.exceptions import ConfigError
from src.claude_pm.infrastructure.permissions import (
    REQUIRED_PERMISSIONS,
    missing_permissions,
    register_permissions,
)


def _settings(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestMissingPermissions:
    def test_absent_file_means_everything_is_missing(self, tmp_path: Path) -> None:
        assert missing_permissions(tmp_path / "none.json") == REQUIRED_PERMISSIONS

    def test_corrupt_file_is_treated_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        assert missing_permissions(path) == REQUIRED_PERMISSIONS

    def test_nothing_missing_when_all_present(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {"permissions": {"allow": list(REQUIRED_PERMISSIONS)}})
        assert missing_permissions(path) == []

    def test_reports_only_what_is_absent(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {"permissions": {"allow": [REQUIRED_PERMISSIONS[0]]}})
        assert missing_permissions(path) == REQUIRED_PERMISSIONS[1:]


class TestRegister:
    def test_adds_the_missing_entries(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {})
        added, still_missing = register_permissions(path)
        assert added == REQUIRED_PERMISSIONS
        assert still_missing == []
        allow = json.loads(path.read_text(encoding="utf-8"))["permissions"]["allow"]
        assert set(REQUIRED_PERMISSIONS).issubset(allow)

    def test_is_idempotent(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {})
        register_permissions(path)
        assert register_permissions(path) == ([], [])

    def test_a_clobbered_write_is_reported_not_claimed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Code owns settings.json and rewrites it while we run."""
        path = _settings(tmp_path, {})
        original = Path.write_text

        def clobber(self: Path, *args: object, **kwargs: object) -> int:
            result = original(self, *args, **kwargs)
            original(self, json.dumps({"permissions": {"allow": []}}), encoding="utf-8")
            return result

        monkeypatch.setattr(Path, "write_text", clobber)
        added, still_missing = register_permissions(path)
        assert added == []
        assert still_missing == REQUIRED_PERMISSIONS

    def test_preserves_unrelated_settings(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            {"model": "opus", "permissions": {"allow": ["Bash(ls)"], "deny": ["Bash(rm)"]}},
        )
        register_permissions(path)
        settings = json.loads(path.read_text(encoding="utf-8"))
        assert settings["model"] == "opus"
        assert settings["permissions"]["deny"] == ["Bash(rm)"]
        assert "Bash(ls)" in settings["permissions"]["allow"]

    def test_does_not_touch_the_file_when_nothing_is_missing(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {"permissions": {"allow": list(REQUIRED_PERMISSIONS)}})
        before = path.read_text(encoding="utf-8")
        register_permissions(path)
        assert path.read_text(encoding="utf-8") == before

    def test_the_permission_targets_the_console_script(self) -> None:
        """Installed via uv there is no pm.py path to allow — it is the `pm` command."""
        assert "Bash(pm:*)" in REQUIRED_PERMISSIONS


class TestRegisterRefusesUnreadableSettings:
    def test_a_corrupt_file_is_refused_and_left_untouched(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text('{"model": "opus", broken', encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid JSON"):
            register_permissions(path)
        assert path.read_text(encoding="utf-8") == '{"model": "opus", broken'

    def test_a_non_object_file_is_refused(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, [])  # type: ignore[arg-type]
        with pytest.raises(ConfigError, match="JSON object"):
            register_permissions(path)

    def test_a_non_list_allow_is_a_config_error(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, {"permissions": {"allow": "Bash(ls)"}})
        with pytest.raises(ConfigError, match="not a list"):
            register_permissions(path)
