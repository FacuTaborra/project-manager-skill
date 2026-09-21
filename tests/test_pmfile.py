"""Parsing and validation of `.pm.toml`."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.claude_pm.enums import ProviderType
from src.claude_pm.exceptions import ConfigError
from src.claude_pm.pmfile import load_pm_file, parse_pm_file

VALID = """
version  = 1
provider = "clickup"
profile  = "4plus"

[scope]
workspace_id   = "9013377000"
workspace_name = "Hemisphere"
space_id       = "90130521234"
space_name     = "4plus"
lists = [
  { id = "901305678901", name = "modulo-energia" },
]

[defaults]
labels   = ["alerts-api"]
state    = "Backlog"
priority = 3
"""

MINIMAL = """
provider = "linear"
profile  = "personal"

[scope]
workspace_id = "org-1"
space_id     = "team-1"
lists = [{ id = "proj-1", name = "alerts" }]
"""


def _parse(text: str, tmp_path: Path):
    return parse_pm_file(text, path=tmp_path / ".pm.toml")


class TestValid:
    def test_reads_every_field(self, tmp_path: Path) -> None:
        pm = _parse(VALID, tmp_path)
        assert pm.provider is ProviderType.CLICKUP
        assert pm.profile == "4plus"
        assert pm.scope.workspace_id == "9013377000"
        assert pm.scope.space_name == "4plus"
        assert pm.scope.lists[0].name == "modulo-energia"
        assert pm.scope.list_ids == {"901305678901"}
        assert pm.defaults.labels == ("alerts-api",)
        assert pm.defaults.state == "Backlog"
        assert pm.defaults.priority == 3

    def test_defaults_are_optional(self, tmp_path: Path) -> None:
        pm = _parse(MINIMAL, tmp_path)
        assert pm.defaults.labels == ()
        assert pm.defaults.state is None
        assert pm.defaults.priority is None

    def test_describe_prefers_names_over_ids(self, tmp_path: Path) -> None:
        assert _parse(VALID, tmp_path).scope.describe() == ("Hemisphere → 4plus → modulo-energia")

    def test_describe_falls_back_to_ids(self, tmp_path: Path) -> None:
        assert _parse(MINIMAL, tmp_path).scope.describe() == "org-1 → team-1 → alerts"


class TestRejections:
    """Every message has to say what to do next — these files are hand-edited."""

    def test_unknown_top_level_key(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="unknown key"):
            _parse(MINIMAL + '\nlabel = "alerts-api"\n', tmp_path)

    def test_unknown_scope_key(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"unknown key\(s\) in \[scope\]"):
            _parse(MINIMAL.replace("space_id", "space", 1), tmp_path)

    def test_unknown_defaults_key(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"\[defaults\]"):
            _parse(MINIMAL + '\n[defaults]\ntag = "x"\n', tmp_path)

    def test_missing_scope(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"missing the \[scope\] table"):
            _parse('provider = "linear"\nprofile = "p"\n', tmp_path)

    def test_missing_profile(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="`profile` is required"):
            _parse(MINIMAL.replace('profile  = "personal"', ""), tmp_path)

    def test_unknown_provider(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="unknown provider"):
            _parse(MINIMAL.replace("linear", "jira"), tmp_path)

    def test_empty_lists_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="nowhere to write"):
            _parse(
                MINIMAL.replace('lists = [{ id = "proj-1", name = "alerts" }]', "lists = []"),
                tmp_path,
            )

    def test_duplicate_list_id(self, tmp_path: Path) -> None:
        dupe = MINIMAL.replace(
            'lists = [{ id = "proj-1", name = "alerts" }]',
            'lists = [{ id = "p", name = "a" }, { id = "p", name = "b" }]',
        )
        with pytest.raises(ConfigError, match="twice"):
            _parse(dupe, tmp_path)

    def test_priority_out_of_range(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="must be 0-4"):
            _parse(MINIMAL + "\n[defaults]\npriority = 9\n", tmp_path)

    def test_unsupported_version(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="unsupported version"):
            _parse("version = 2\n" + MINIMAL, tmp_path)

    def test_malformed_toml(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not valid TOML"):
            _parse("provider = ", tmp_path)


class TestLoad:
    def test_missing_file_points_at_pm_init(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with pytest.raises(ConfigError, match="pm init"):
            load_pm_file(tmp_path)

    def test_repo_root_is_the_git_root_not_the_pm_file_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "services" / "api"
        nested.mkdir(parents=True)
        (nested / ".pm.toml").write_text(MINIMAL, encoding="utf-8")
        assert load_pm_file(nested).repo_root == tmp_path.resolve()
