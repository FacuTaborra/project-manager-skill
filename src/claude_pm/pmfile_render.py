"""Emit `.pm.toml`.

The standard library reads TOML but does not write it, and the schema here is
small and fixed, so a template beats taking on a dependency in a package that
has none. `tests/test_init_flow.py` closes the loop by parsing what this emits.

Lives next to `pmfile.py`, which parses what this renders.
"""

from __future__ import annotations

from .pmfile import PM_FILE_VERSION, Defaults, ScopeSpec


def render_pm_toml(
    *,
    provider: str,
    profile: str,
    scope: ScopeSpec,
    defaults: Defaults | None = None,
) -> str:
    defaults = defaults or Defaults()
    lines = [
        "# Which board this repo writes to. Committed — the whole team shares it.",
        "# Secrets live in ~/.claude/pm/credentials.toml, never here.",
        "",
        f"version  = {PM_FILE_VERSION}",
        f"provider = {toml_string(provider)}",
        f"profile  = {toml_string(profile)}",
        "",
        "# The allowlist. Nothing outside it can be written to.",
        "[scope]",
        f"workspace_id   = {toml_string(scope.workspace_id)}",
        f"workspace_name = {toml_string(scope.workspace_name)}",
        f"space_id       = {toml_string(scope.space_id)}",
        f"space_name     = {toml_string(scope.space_name)}",
        "lists = [",
    ]
    lines.extend(
        f"  {{ id = {toml_string(ref.id)}, name = {toml_string(ref.name)} }},"
        for ref in scope.lists
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


def toml_string(value: str) -> str:
    """Render `value` as a quoted TOML basic string, escaping `\\` and `"`.

    Shared with `credentials.py`, which writes profile fields (token, provider,
    workspace_id) into the same file format and must not let an unescaped quote
    or backslash in a token break the TOML it writes.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
