"""The invariant that makes the chokepoint real.

`services/scope_guard.py` is the only module allowed to call a provider's mutating
methods. Everything else must go through the guard. If that stops being true,
`--dry-run` silently stops being total and scope checks become skippable, so the
rule is checked mechanically rather than left to review.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "claude_pm"

MUTATORS = {
    "create_issue",
    "update_issue",
    "create_project",
    "create_team",
    "create_doc",
    "update_doc",
    "create_label",
}

# scope_guard.py *is* the chokepoint; the providers declare and implement the contract.
EXEMPT_FILES = {"services/scope_guard.py"}
EXEMPT_DIRS = ("repositories/providers/",)


def _is_guard(node: ast.expr) -> bool:
    """True when the receiver is the guard — the one object allowed to mutate."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "get_scope_guard"
    if isinstance(node, ast.Name):
        return node.id == "guard"
    if isinstance(node, ast.Attribute):
        return node.attr == "guard"
    return False


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in MUTATORS and not _is_guard(func.value):
            found.append(f"line {node.lineno}: .{func.attr}(...)")
    return found


def _modules() -> list[Path]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in EXEMPT_FILES or rel.startswith(EXEMPT_DIRS):
            continue
        out.append(path)
    return out


def test_only_the_guard_calls_mutating_provider_methods() -> None:
    offences = {
        path.relative_to(SRC).as_posix(): found for path in _modules() if (found := _offences(path))
    }
    assert not offences, (
        "These modules mutate outside services/scope_guard.py, which defeats the scope "
        f"check and --dry-run: {offences}"
    )


def test_the_check_would_actually_catch_something(tmp_path: Path) -> None:
    """Guard against the invariant quietly matching nothing."""
    offender = tmp_path / "offender.py"
    offender.write_text("provider.create_issue(draft)\n", encoding="utf-8")
    assert _offences(offender)

    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "guard.create_issue(title='x')\n"
        "self.guard.update_issue(u)\n"
        "get_scope_guard(args).create_doc(title='x')\n",
        encoding="utf-8",
    )
    assert not _offences(innocent)


def test_the_guard_itself_is_covered_by_the_exemption() -> None:
    """If scope_guard.py were renamed, the exemption must be updated with it."""
    assert (SRC / "services" / "scope_guard.py").is_file()
