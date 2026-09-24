"""What commands print: JSON on stdout, human notes on stderr."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from ..config import credentials_path
from ..models.tracker import Briefing, Issue, Workspace
from ..services.scope_guard import DryRun


def issue_to_dict(issue: Issue, *, with_description: bool = False) -> dict[str, Any]:
    payload = {
        "identifier": issue.identifier,
        "title": issue.title,
        "priority": issue.priority,
        "url": issue.url,
        "state": {"id": issue.state.id, "name": issue.state.name},
        "project": (
            {"id": issue.project.id, "name": issue.project.name} if issue.project else None
        ),
    }
    if with_description:
        payload["description"] = issue.description
    return payload


def issues_by_state_to_dict(grouped: dict[str, list[Issue]]) -> dict[str, list[dict[str, Any]]]:
    return {state: [issue_to_dict(i) for i in issues] for state, issues in grouped.items()}


def briefing_to_dict(briefing: Briefing) -> dict[str, Any]:
    return {
        "repo": briefing.repo_name,
        "project": briefing.project_name,
        "issues_by_state": issues_by_state_to_dict(briefing.issues_by_state),
        "total_open": briefing.total_open,
    }


def print_write_outcome(outcome: Any, to_json: Callable[[Any], dict[str, Any]]) -> None:
    """Print a dry-run preview, or the real result via `to_json`."""
    if isinstance(outcome, DryRun):
        print_json(outcome.to_dict())
    else:
        print_json(to_json(outcome))


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_profile_saved(
    name: str, email: str, reachable: list[Workspace], workspace_id: str | None
) -> None:
    print(f"  ✓ token valid — authenticated as {email}", file=sys.stderr)
    print(
        f"  ✓ reaches {len(reachable)} workspace(s): "
        + ", ".join(f"{w.name} ({w.id})" for w in reachable),
        file=sys.stderr,
    )
    if workspace_id:
        print(f"  ✓ profile pinned to {workspace_id}", file=sys.stderr)
    print(f"  ✓ profile {name!r} written to {credentials_path()}", file=sys.stderr)
