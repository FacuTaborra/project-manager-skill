"""Cache v2: fingerprint keying, freshness, and refusal to read older formats."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.claude_pm.infrastructure.cache import (
    CACHE_TTL_DAYS,
    CACHE_VERSION,
    Cache,
    JsonFileCacheRepository,
    find_legacy_caches,
)
from tests.fakes import InMemoryCacheRepository

FINGERPRINT = "a1b2c3d4"
LISTS = [{"id": "901305678901", "name": "modulo-energia"}]
STATES = {"Backlog": "Backlog", "in progress": "in progress"}
LABELS = [{"id": "alerts-api", "name": "alerts-api"}]


def _ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _complete(**overrides) -> Cache:
    base = dict(
        fingerprint=FINGERPRINT,
        team_id="90130521234",
        team_name="4plus",
        projects=tuple(LISTS),
        state_id_by_name=STATES,
        last_refresh=_ago(1),
    )
    base.update(overrides)
    return Cache(**base)


class TestFreshness:
    def test_recent_is_fresh(self) -> None:
        assert Cache(last_refresh=_ago(1)).is_fresh()

    def test_expired_is_not(self) -> None:
        assert not Cache(last_refresh=_ago(CACHE_TTL_DAYS + 1)).is_fresh()

    def test_missing_timestamp_is_not(self) -> None:
        assert not Cache().is_fresh()

    def test_garbage_timestamp_is_not(self) -> None:
        assert not Cache(last_refresh="ayer").is_fresh()


class TestValidity:
    def test_complete_fresh_and_matching(self) -> None:
        assert _complete().is_valid_for(FINGERPRINT)

    def test_a_different_fingerprint_is_never_valid(self) -> None:
        assert not _complete().is_valid_for("ffffffff")

    def test_incomplete_is_not_valid(self) -> None:
        assert not _complete(state_id_by_name={}).is_valid_for(FINGERPRINT)

    def test_stale_is_not_valid(self) -> None:
        assert not _complete(last_refresh=_ago(CACHE_TTL_DAYS + 1)).is_valid_for(FINGERPRINT)


class TestLookups:
    def test_list_name_by_id(self) -> None:
        assert _complete().project_name("901305678901") == "modulo-energia"

    def test_unknown_list_id(self) -> None:
        assert _complete().project_name("nope") is None

    def test_label_names(self) -> None:
        assert _complete(labels=tuple(LABELS)).label_names() == ("alerts-api",)


class TestJsonFileRepository:
    def test_round_trip(self, tmp_path: Path) -> None:
        repo = JsonFileCacheRepository(tmp_path / "c.json", FINGERPRINT)
        written = repo.write(
            space_id="90130521234",
            space_name="4plus",
            lists=LISTS,
            state_ids=STATES,
            labels=LABELS,
        )
        assert written.team_id == "90130521234"
        loaded = repo.load()
        assert loaded.projects == tuple(LISTS)
        assert loaded.state_id_by_name == STATES
        assert loaded.labels == tuple(LABELS)
        assert loaded.fingerprint == FINGERPRINT

    def test_absent_file_loads_empty(self, tmp_path: Path) -> None:
        assert JsonFileCacheRepository(tmp_path / "none.json", FINGERPRINT).load() == Cache()

    def test_corrupt_file_loads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{not json", encoding="utf-8")
        assert JsonFileCacheRepository(path, FINGERPRINT).load() == Cache()

    def test_v1_format_is_ignored_not_migrated(self, tmp_path: Path) -> None:
        """v1 was keyed by basename, so its binding was never validated."""
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps(
                {
                    "linearTeamId": "old-team",
                    "linearProjectId": "old-project",
                    "stateIds": {"Todo": "x"},
                    "lastRefresh": _ago(1),
                }
            ),
            encoding="utf-8",
        )
        assert JsonFileCacheRepository(path, FINGERPRINT).load() == Cache()

    def test_a_foreign_fingerprint_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        JsonFileCacheRepository(path, "other-fp").write(
            space_id="s", space_name="n", lists=LISTS, state_ids=STATES
        )
        assert JsonFileCacheRepository(path, FINGERPRINT).load() == Cache()

    def test_creates_missing_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "deeper" / "c.json"
        JsonFileCacheRepository(path, FINGERPRINT).write(
            space_id="s", space_name="n", lists=LISTS, state_ids=STATES
        )
        assert path.is_file()

    def test_writes_the_current_version(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        JsonFileCacheRepository(path, FINGERPRINT).write(
            space_id="s", space_name="n", lists=LISTS, state_ids=STATES
        )
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == CACHE_VERSION

    def test_malformed_list_entries_are_dropped(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "fingerprint": FINGERPRINT,
                    "space_id": "s",
                    "lists": [{"id": "ok", "name": "fine"}, {"id": "missing-name"}, "junk"],
                    "state_ids": {},
                    "last_refresh": _ago(1),
                }
            ),
            encoding="utf-8",
        )
        assert JsonFileCacheRepository(path, FINGERPRINT).load().projects == (
            {"id": "ok", "name": "fine"},
        )


class TestInMemoryRepository:
    def test_starts_empty(self) -> None:
        assert InMemoryCacheRepository().load() == Cache()

    def test_write_then_load(self) -> None:
        repo = InMemoryCacheRepository()
        repo.write(space_id="s", space_name="n", lists=LISTS, state_ids=STATES, labels=LABELS)
        loaded = repo.load()
        assert loaded.team_id == "s"
        assert loaded.labels == tuple(LABELS)


class TestLegacyDiscovery:
    def test_finds_orphaned_v1_files(self, tmp_path: Path) -> None:
        old = tmp_path / "proyectos" / "alerts-api"
        old.mkdir(parents=True)
        (old / ".clickup-cache.json").write_text("{}", encoding="utf-8")
        assert find_legacy_caches(tmp_path) == [old / ".clickup-cache.json"]

    def test_no_vault_means_nothing_to_report(self) -> None:
        assert find_legacy_caches(None) == []

    def test_vault_without_projects_dir(self, tmp_path: Path) -> None:
        assert find_legacy_caches(tmp_path) == []
