"""`.pm.toml` is committed and secret-free; without one there are no writes.

The stdlib reads TOML but cannot write it and the schema is small, so rendering is a template.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ..config import PM_FILE_NAME
from ..enums import ProviderType
from ..exceptions import ConfigError
from ..models.repo_config import IssueDefaults, PmFile, ProjectRef, Scope
from .git_repo import find_pm_file, find_repo_root
from .toml import reject_unknown_keys, toml_string

PM_FILE_VERSION = 1

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

_MIN_PRIORITY = 0
_MAX_PRIORITY = 4

_INIT_HINT = f"Run `pm init` in the repo root to write a {PM_FILE_NAME}."


def load_pm_file(start: Path | None = None) -> PmFile:
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

    reject_unknown_keys(raw, _TOP_LEVEL_KEYS, path, "top level")

    version = _require_int(raw.get("version", PM_FILE_VERSION), "version", path)
    if version != PM_FILE_VERSION:
        raise ConfigError(
            f"{path}: unsupported version {version} (this build understands {PM_FILE_VERSION}). "
            "Upgrade pm, or re-run `pm init --force`."
        )

    provider = _parse_provider(raw.get("provider"), path)
    profile = _require_str(raw.get("profile"), "profile", path, required=True)

    scope_raw = raw.get("scope")
    if not isinstance(scope_raw, dict):
        raise ConfigError(f"{path}: missing the [scope] table. {_INIT_HINT}")
    scope = _parse_scope(scope_raw, path)

    defaults_raw = raw.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        raise ConfigError(f"{path}: [defaults] must be a table.")
    defaults = _parse_defaults(defaults_raw, path)

    return PmFile(
        path=path,
        repo_root=find_repo_root(path.parent) or path.parent,
        provider_type=provider,
        profile_name=profile,
        scope=scope,
        defaults=defaults,
    )


def _parse_scope(raw: dict[str, Any], path: Path) -> Scope:
    reject_unknown_keys(raw, _SCOPE_KEYS, path, "[scope]")

    workspace_id = _require_str(raw.get("workspace_id"), "scope.workspace_id", path, required=True)
    team_id = _require_str(raw.get("space_id"), "scope.space_id", path, required=True)

    lists_raw = raw.get("lists")
    if not isinstance(lists_raw, list) or not lists_raw:
        raise ConfigError(
            f"{path}: [scope].lists must be a non-empty array of {{ id, name }} tables. "
            "Without at least one list there is nowhere to write."
        )

    projects: list[ProjectRef] = []
    seen: set[str] = set()
    for index, entry in enumerate(lists_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: [scope].lists[{index}] must be a {{ id, name }} table.")
        reject_unknown_keys(entry, _LIST_KEYS, path, f"[scope].lists[{index}]")
        list_id = _require_str(entry.get("id"), f"scope.lists[{index}].id", path, required=True)
        if list_id in seen:
            raise ConfigError(f"{path}: [scope].lists has {list_id} twice.")
        seen.add(list_id)
        projects.append(
            ProjectRef(
                id=list_id, name=_require_str(entry.get("name"), f"scope.lists[{index}].name", path)
            )
        )

    return Scope(
        workspace_id=workspace_id,
        team_id=team_id,
        projects=tuple(projects),
        workspace_name=_require_str(raw.get("workspace_name"), "scope.workspace_name", path),
        team_name=_require_str(raw.get("space_name"), "scope.space_name", path),
    )


def _parse_defaults(raw: dict[str, Any], path: Path) -> IssueDefaults:
    reject_unknown_keys(raw, _DEFAULTS_KEYS, path, "[defaults]")

    labels_raw = raw.get("labels", [])
    if not isinstance(labels_raw, list):
        raise ConfigError(f"{path}: [defaults].labels must be an array of strings.")
    labels: list[str] = []
    for entry in labels_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigError(f"{path}: [defaults].labels must hold non-empty strings.")
        labels.append(entry.strip())

    priority_raw = raw.get("priority")
    priority = (
        None if priority_raw is None else _require_int(priority_raw, "defaults.priority", path)
    )
    if priority is not None and not _MIN_PRIORITY <= priority <= _MAX_PRIORITY:
        raise ConfigError(
            f"{path}: [defaults].priority must be {_MIN_PRIORITY}-{_MAX_PRIORITY} (got {priority})."
        )

    return IssueDefaults(
        labels=tuple(labels),
        state=_require_str(raw.get("state"), "defaults.state", path) or None,
        priority=priority,
    )


def _parse_provider(value: Any, path: Path) -> ProviderType:
    if value is None:
        raise ConfigError(f"{path}: missing `provider`. {_INIT_HINT}")

    return ProviderType.parse(value, where=f"{path}: ", error=ConfigError)


def _require_str(value: Any, name: str, path: Path, *, required: bool = False) -> str:
    if value is None or value == "":
        if required:
            raise ConfigError(f"{path}: `{name}` is required. {_INIT_HINT}")
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{path}: `{name}` must be a string, got {type(value).__name__}.")
    return value.strip()


def _require_int(value: Any, name: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}: `{name}` must be an integer, got {type(value).__name__}.")
    return value


def render_pm_toml(
    *,
    provider_name: str,
    profile_name: str,
    scope: Scope,
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
