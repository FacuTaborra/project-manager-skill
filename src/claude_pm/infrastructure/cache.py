"""Local JSON cache of the ids discovered for one (repo, profile, board) triple.

The cache is pure derived state: deleting it costs two or three API calls. It is
keyed by the config fingerprint, which is part of its filename, so switching
profile, workspace, space or list lands on a different file. That is the whole
invalidation story — there is no invalidation logic to get wrong.

Anything written by an older build is ignored rather than migrated: the bug in
v1 *was* its key, so importing it would mean trusting a binding that was never
validated.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

CACHE_TTL_DAYS = 30
CACHE_VERSION = 2


def cache_root() -> Path:
    """Where machine state lives — never the Obsidian vault, which is for humans."""
    env = os.environ.get("PM_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "claude-pm"
    return Path.home() / ".cache" / "claude-pm"


@dataclass(frozen=True)
class Cache:
    """Immutable snapshot of cached provider ids."""

    fingerprint: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    projects: tuple[dict[str, str], ...] = field(default_factory=tuple)
    state_id_by_name: dict[str, str] = field(default_factory=dict)
    labels: tuple[dict[str, str], ...] = field(default_factory=tuple)
    last_refresh: str | None = None

    def is_fresh(self) -> bool:
        if not self.last_refresh:
            return False
        try:
            last = datetime.fromisoformat(self.last_refresh.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (datetime.now(UTC) - last).days < CACHE_TTL_DAYS

    def is_complete(self) -> bool:
        return bool(self.team_id and self.projects and self.state_id_by_name)

    def is_valid_for(self, fingerprint: str) -> bool:
        return self.fingerprint == fingerprint and self.is_complete() and self.is_fresh()

    def project_name(self, list_id: str) -> str | None:
        return next((e["name"] for e in self.projects if e["id"] == list_id), None)

    def label_names(self) -> tuple[str, ...]:
        return tuple(e["name"] for e in self.labels)


class CacheRepository(Protocol):
    def load(self) -> Cache: ...

    def write(
        self,
        *,
        team_id: str,
        team_name: str,
        projects: list[dict[str, str]],
        state_id_by_name: dict[str, str],
        labels: list[dict[str, str]] | None = None,
    ) -> Cache: ...


class JsonFileCacheRepository:
    def __init__(self, path: Path, fingerprint: str) -> None:
        self.path = path
        self.fingerprint = fingerprint

    def load(self) -> Cache:
        if not self.path.is_file():
            return Cache()
        try:
            data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Cache()
        if data.get("version") != CACHE_VERSION or data.get("fingerprint") != self.fingerprint:
            return Cache()
        return _cache_from_dict(data)

    def write(
        self,
        *,
        team_id: str,
        team_name: str,
        projects: list[dict[str, str]],
        state_id_by_name: dict[str, str],
        labels: list[dict[str, str]] | None = None,
    ) -> Cache:
        now = datetime.now(UTC).isoformat()
        data: dict[str, Any] = {
            "version": CACHE_VERSION,
            "fingerprint": self.fingerprint,
            "space_id": team_id,
            "space_name": team_name,
            "lists": projects,
            "state_ids": state_id_by_name,
            "labels": labels or [],
            "last_refresh": now,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return _cache_from_dict(data)


def _cache_from_dict(data: dict[str, Any]) -> Cache:
    raw_states = data.get("state_ids", {})
    return Cache(
        fingerprint=_opt_str(data.get("fingerprint")),
        team_id=_opt_str(data.get("space_id")),
        team_name=_opt_str(data.get("space_name")),
        projects=_pairs(data.get("lists")),
        state_id_by_name=(
            {str(k): str(v) for k, v in raw_states.items()} if isinstance(raw_states, dict) else {}
        ),
        labels=_pairs(data.get("labels")),
        last_refresh=_opt_str(data.get("last_refresh")),
    )


def _pairs(raw: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, dict) and "id" in entry and "name" in entry:
            out.append({"id": str(entry["id"]), "name": str(entry["name"])})
    return tuple(out)


def _opt_str(value: Any) -> str | None:
    return str(value) if value else None
