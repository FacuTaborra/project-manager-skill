"""Parse `<repo>/.pm.toml` — the repo's binding to a board.

This file is committed, so the whole team inherits the same binding. It holds no
secrets: the `profile` key names a credential in `~/.claude/pm/credentials.toml`.

Its presence is the first barrier. No `.pm.toml`, no writes.

Unknown keys are rejected rather than ignored. The old INI format silently
dropped anything it did not recognise, which is how its `label:` key sat there
doing nothing for months.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .enums import ProviderType
from .exceptions import ConfigError
from .infrastructure.repo_detect import PM_FILE_NAME, find_pm_file, find_repo_root

SUPPORTED_VERSION = 1

_TOP_LEVEL_KEYS = {"version", "provider", "profile", "scope", "defaults"}
_SCOPE_KEYS = {
    "workspace_id",
    "workspace_name",
    "space_id",
    "space_name",
    "lists",
}
_DEFAULTS_KEYS = {"labels", "state", "priority"}
_LIST_KEYS = {"id", "name"}

_INIT_HINT = f"Run `pm init` in the repo root to write a {PM_FILE_NAME}."


@dataclass(frozen=True)
class ListRef:
    """A writable destination: a ClickUp list or a Linear project."""

    id: str
    name: str


@dataclass(frozen=True)
class ScopeSpec:
    """The allowlist. Nothing outside it can be written to.

    The `*_name` fields never resolve anything — the ids do. They exist so errors
    can name the board a human recognises, and so drift is detectable when
    someone renames it in the tracker.
    """

    workspace_id: str
    space_id: str
    lists: tuple[ListRef, ...]
    workspace_name: str = ""
    space_name: str = ""

    @property
    def list_ids(self) -> frozenset[str]:
        return frozenset(ref.id for ref in self.lists)

    def describe(self) -> str:
        names = ", ".join(ref.name or ref.id for ref in self.lists)
        return f"{self.workspace_name or self.workspace_id} → {self.space_name or self.space_id} → {names}"


@dataclass(frozen=True)
class Defaults:
    """Applied to every issue created from this repo."""

    labels: tuple[str, ...] = ()
    state: str | None = None
    priority: int | None = None


@dataclass(frozen=True)
class PmFile:
    path: Path
    repo_root: Path
    provider: ProviderType
    profile: str
    scope: ScopeSpec
    defaults: Defaults = field(default_factory=Defaults)
    version: int = SUPPORTED_VERSION


def load_pm_file(start: Path | None = None) -> PmFile:
    """Find and parse the nearest `.pm.toml`, or explain how to create one."""
    path = find_pm_file(start)
    if path is None:
        where = (start or Path.cwd()).resolve()
        raise ConfigError(
            f"No {PM_FILE_NAME} found for {where}.\n"
            f"This repo is not bound to a board yet. {_INIT_HINT}"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    return parse_pm_file(text, path=path)


def parse_pm_file(text: str, *, path: Path) -> PmFile:
    try:
        raw: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    _reject_unknown(raw, _TOP_LEVEL_KEYS, path, "top level")

    version = _int(raw.get("version", SUPPORTED_VERSION), "version", path)
    if version != SUPPORTED_VERSION:
        raise ConfigError(
            f"{path}: unsupported version {version} (this build understands {SUPPORTED_VERSION}). "
            "Upgrade pm, or re-run `pm init --force`."
        )

    provider = _provider(raw.get("provider"), path)
    profile = _str(raw.get("profile"), "profile", path, required=True)

    scope_raw = raw.get("scope")
    if not isinstance(scope_raw, dict):
        raise ConfigError(f"{path}: missing the [scope] table. {_INIT_HINT}")
    scope = _scope(scope_raw, path)

    defaults_raw = raw.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        raise ConfigError(f"{path}: [defaults] must be a table.")
    defaults = _defaults(defaults_raw, path)

    repo_root = find_repo_root(path.parent) or path.parent
    return PmFile(
        path=path,
        repo_root=repo_root,
        provider=provider,
        profile=profile,
        scope=scope,
        defaults=defaults,
        version=version,
    )


def _scope(raw: dict[str, Any], path: Path) -> ScopeSpec:
    _reject_unknown(raw, _SCOPE_KEYS, path, "[scope]")

    workspace_id = _str(raw.get("workspace_id"), "scope.workspace_id", path, required=True)
    space_id = _str(raw.get("space_id"), "scope.space_id", path, required=True)

    lists_raw = raw.get("lists")
    if not isinstance(lists_raw, list) or not lists_raw:
        raise ConfigError(
            f"{path}: [scope].lists must be a non-empty array of {{ id, name }} tables. "
            "Without at least one list there is nowhere to write."
        )

    lists: list[ListRef] = []
    seen: set[str] = set()
    for index, entry in enumerate(lists_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: [scope].lists[{index}] must be a {{ id, name }} table.")
        _reject_unknown(entry, _LIST_KEYS, path, f"[scope].lists[{index}]")
        list_id = _str(entry.get("id"), f"scope.lists[{index}].id", path, required=True)
        if list_id in seen:
            raise ConfigError(f"{path}: [scope].lists has {list_id} twice.")
        seen.add(list_id)
        lists.append(ListRef(id=list_id, name=_str(entry.get("name"), "", path) or ""))

    return ScopeSpec(
        workspace_id=workspace_id,
        space_id=space_id,
        lists=tuple(lists),
        workspace_name=_str(raw.get("workspace_name"), "", path) or "",
        space_name=_str(raw.get("space_name"), "", path) or "",
    )


def _defaults(raw: dict[str, Any], path: Path) -> Defaults:
    _reject_unknown(raw, _DEFAULTS_KEYS, path, "[defaults]")

    labels_raw = raw.get("labels", [])
    if not isinstance(labels_raw, list):
        raise ConfigError(f"{path}: [defaults].labels must be an array of strings.")
    labels: list[str] = []
    for entry in labels_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigError(f"{path}: [defaults].labels must hold non-empty strings.")
        labels.append(entry.strip())

    priority_raw = raw.get("priority")
    priority = None if priority_raw is None else _int(priority_raw, "defaults.priority", path)
    if priority is not None and not 0 <= priority <= 4:
        raise ConfigError(f"{path}: [defaults].priority must be 0-4 (got {priority}).")

    return Defaults(
        labels=tuple(labels),
        state=_str(raw.get("state"), "", path) or None,
        priority=priority,
    )


def _provider(value: Any, path: Path) -> ProviderType:
    if value is None:
        raise ConfigError(f"{path}: missing `provider`. {_INIT_HINT}")
    try:
        return ProviderType(value)
    except (ValueError, TypeError):
        supported = ", ".join(p.value for p in ProviderType)
        raise ConfigError(f"{path}: unknown provider {value!r}. Supported: {supported}.") from None


def _reject_unknown(raw: dict[str, Any], allowed: set[str], path: Path, where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) in {where}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )


def _str(value: Any, name: str, path: Path, *, required: bool = False) -> str:
    if value is None or value == "":
        if required:
            raise ConfigError(f"{path}: `{name}` is required. {_INIT_HINT}")
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{path}: `{name}` must be a string, got {type(value).__name__}.")
    return value.strip()


def _int(value: Any, name: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}: `{name}` must be an integer, got {type(value).__name__}.")
    return value
