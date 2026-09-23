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
        space_id: str,
        space_name: str,
        lists: list[dict[str, str]],
        state_ids: dict[str, str],
        labels: list[dict[str, str]] | None = None,
    ) -> Cache:
        self._cache = Cache(
            fingerprint=self._cache.fingerprint,
            space_id=space_id,
            space_name=space_name,
            lists=tuple(lists),
            state_ids=state_ids,
            labels=tuple(labels or []),
            last_refresh=datetime.now(UTC).isoformat(),
        )
        return self._cache
