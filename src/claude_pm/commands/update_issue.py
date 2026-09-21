"""`update-issue` — update an issue, but only one this repo is allowed to touch."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..domain.models import IssueUpdate
from ..exceptions import EXIT_OK, PMError
from ._helpers import prepare_write, print_result


def run(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)

    description: str | None = args.description
    if args.description_file:
        path = Path(args.description_file).expanduser()
        if not path.is_file():
            raise PMError(f"Description file not found: {path}")
        description = path.read_text(encoding="utf-8")

    state_id = guard.resolve_state_id(args.state)
    assignee_id = guard.resolve_assignee_id(args.assignee)

    update = IssueUpdate(
        issue_id=args.id,
        title=args.title,
        description=description,
        state_id=state_id,
        priority=args.priority,
        assignee_id=assignee_id,
    )
    if not any(
        value is not None
        for value in (update.title, update.description, state_id, update.priority, assignee_id)
    ):
        raise PMError(
            "Nothing to update — pass at least one of --title/--description/--state/--priority/--assignee."
        )

    print_result(
        guard.update_issue(update),
        lambda issue: {
            "ok": True,
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state.name,
            "url": issue.url,
        },
    )
    return EXIT_OK
