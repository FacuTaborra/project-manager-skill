"""Emit `.pm.toml`.

The standard library reads TOML but does not write it, and the schema here is
small and fixed, so a template beats taking on a dependency in a package that
has none. `tests/test_init_flow.py` closes the loop by parsing what this emits.
"""

from __future__ import annotations

from ..pmfile import SUPPORTED_VERSION, Defaults, ScopeSpec


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
        f"version  = {SUPPORTED_VERSION}",
        f"provider = {_s(provider)}",
        f"profile  = {_s(profile)}",
        "",
        "# The allowlist. Nothing outside it can be written to.",
        "[scope]",
        f"workspace_id   = {_s(scope.workspace_id)}",
        f"workspace_name = {_s(scope.workspace_name)}",
        f"space_id       = {_s(scope.space_id)}",
        f"space_name     = {_s(scope.space_name)}",
        "lists = [",
    ]
    lines.extend(f"  {{ id = {_s(ref.id)}, name = {_s(ref.name)} }}," for ref in scope.lists)
    lines.append("]")

    if defaults.labels or defaults.state or defaults.priority is not None:
        lines.extend(["", "[defaults]"])
        if defaults.labels:
            joined = ", ".join(_s(label) for label in defaults.labels)
            lines.append(f"labels   = [{joined}]")
        if defaults.state:
            lines.append(f"state    = {_s(defaults.state)}")
        if defaults.priority is not None:
            lines.append(f"priority = {defaults.priority}")

    return "\n".join(lines) + "\n"


def _s(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
