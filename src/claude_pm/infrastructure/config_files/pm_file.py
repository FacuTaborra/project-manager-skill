"""Read and write `<repo>/.pm.toml` — the repo's binding to a board.

This file is committed, so the whole team inherits the same binding. It holds no
secrets: the `profile` key names a credential in `~/.claude/pm/credentials.toml`.

Its presence is the first barrier. No `.pm.toml`, no writes.

Unknown keys are rejected rather than ignored. The old INI format silently
dropped anything it did not recognise, which is how its `label:` key sat there
doing nothing for months.

The standard library reads TOML but does not write it, and the schema here is
small and fixed, so a template beats taking on a dependency in a package that
has none. `tests/test_init_flow.py` closes the loop by parsing what `render_pm_toml`
emits.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ...domain.binding import (
    PM_FILE_VERSION,
    IssueDefaults,
    ProviderType,
    RepoBinding,
    ScopeProject,
    WriteScope,
)
from ...exceptions import ConfigError
from ..repo_detect import PM_FILE_NAME, find_pm_file, find_repo_root
from ._toml import reject_unknown, toml_string

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


def load_pm_file(start: Path | None = None) -> RepoBinding:
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


def parse_pm_file(text: str, *, path: Path) -> RepoBinding:
    try:
        raw: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    reject_unknown(raw, _TOP_LEVEL_KEYS, path, "top level")

    version = _int(raw.get("version", PM_FILE_VERSION), "version", path)
    if version != PM_FILE_VERSION:
        raise ConfigError(
            f"{path}: unsupported version {version} (this build understands {PM_FILE_VERSION}). "
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
    return RepoBinding(
        path=path,
        repo_root=repo_root,
        provider_type=provider,
        profile_name=profile,
        scope=scope,
        defaults=defaults,
        version=version,
    )


def _scope(raw: dict[str, Any], path: Path) -> WriteScope:
    reject_unknown(raw, _SCOPE_KEYS, path, "[scope]")

    workspace_id = _str(raw.get("workspace_id"), "scope.workspace_id", path, required=True)
    team_id = _str(raw.get("space_id"), "scope.space_id", path, required=True)

    lists_raw = raw.get("lists")
    if not isinstance(lists_raw, list) or not lists_raw:
        raise ConfigError(
            f"{path}: [scope].lists must be a non-empty array of {{ id, name }} tables. "
            "Without at least one list there is nowhere to write."
        )

    projects: list[ScopeProject] = []
    seen: set[str] = set()
    for index, entry in enumerate(lists_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: [scope].lists[{index}] must be a {{ id, name }} table.")
        reject_unknown(entry, _LIST_KEYS, path, f"[scope].lists[{index}]")
        list_id = _str(entry.get("id"), f"scope.lists[{index}].id", path, required=True)
        if list_id in seen:
            raise ConfigError(f"{path}: [scope].lists has {list_id} twice.")
        seen.add(list_id)
        projects.append(ScopeProject(id=list_id, name=_str(entry.get("name"), "", path) or ""))

    return WriteScope(
        workspace_id=workspace_id,
        team_id=team_id,
        projects=tuple(projects),
        workspace_name=_str(raw.get("workspace_name"), "", path) or "",
        team_name=_str(raw.get("space_name"), "", path) or "",
    )


def _defaults(raw: dict[str, Any], path: Path) -> IssueDefaults:
    reject_unknown(raw, _DEFAULTS_KEYS, path, "[defaults]")

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

    return IssueDefaults(
        labels=tuple(labels),
        state=_str(raw.get("state"), "", path) or None,
        priority=priority,
    )


def _provider(value: Any, path: Path) -> ProviderType:
    if value is None:
        raise ConfigError(f"{path}: missing `provider`. {_INIT_HINT}")
    return ProviderType.parse(value, where=f"{path}: ", error=ConfigError)


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


def render_pm_toml(
    *,
    provider_name: str,
    profile_name: str,
    scope: WriteScope,
    defaults: IssueDefaults | None = None,
) -> str:
    defaults = defaults or IssueDefaults()
    lines = [
        "# Which board this repo writes to. Committed — the whole team shares it.",
        "# Secrets live in ~/.claude/pm/credentials.toml, never here.",
        "",
        f"version  = {PM_FILE_VERSION}",
        f"provider = {toml_string(provider_name)}",
        f"profile  = {toml_string(profile_name)}",
        "",
        "# The allowlist. Nothing outside it can be written to.",
        "[scope]",
        f"workspace_id   = {toml_string(scope.workspace_id)}",
        f"workspace_name = {toml_string(scope.workspace_name)}",
        f"space_id       = {toml_string(scope.team_id)}",
        f"space_name     = {toml_string(scope.team_name)}",
        "lists = [",
    ]
    lines.extend(
        f"  {{ id = {toml_string(ref.id)}, name = {toml_string(ref.name)} }},"
        for ref in scope.projects
    )
    lines.append("]")

    if defaults.labels or defaults.state or defaults.priority is not None:
        lines.extend(["", "[defaults]"])
        if defaults.labels:
            joined = ", ".join(toml_string(label) for label in defaults.labels)
            lines.append(f"labels   = [{joined}]")
        if defaults.state:
            lines.append(f"state    = {toml_string(defaults.state)}")
        if defaults.priority is not None:
            lines.append(f"priority = {defaults.priority}")

    return "\n".join(lines) + "\n"
