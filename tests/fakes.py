"""Test doubles shared across the suite — no filesystem or network I/O."""

from __future__ import annotations

from datetime import UTC, datetime

from src.claude_pm.infrastructure.cache import Cache


class InMemoryCacheRepository:
    """In-memory implementation of CacheRepository for tests."""

    def __init__(self, initial: Cache | None = None) -> None:
        self._cache = initial or Cache()

    def load(self) -> Cache:
        return self._cache

    def write(
        self,
        *,
        team_id: str,
        team_name: str,
        projects: list[dict[str, str]],
        state_id_by_name: dict[str, str],
        labels: list[dict[str, str]] | None = None,
    ) -> Cache:
        self._cache = Cache(
            fingerprint=self._cache.fingerprint,
            team_id=team_id,
            team_name=team_name,
            projects=tuple(projects),
            state_id_by_name=state_id_by_name,
            labels=tuple(labels or []),
            last_refresh=datetime.now(UTC).isoformat(),
        )
        return self._cache
