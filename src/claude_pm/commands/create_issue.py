"""`create-issue` — create a single issue inside this repo's declared scope."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..exceptions import EXIT_OK, PMError
from ._helpers import prepare_write, print_result


def run(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)

    outcome = guard.create_issue(
        title=args.title,
        description=_description(args),
        list_id=args.project_id,
        state=args.state,
        priority=args.priority,
        assignee_email=args.assignee,
        labels=args.label or [],
    )
    print_result(
        outcome,
        lambda issue: {
            "ok": True,
            "id": issue.identifier,
            "identifier": issue.identifier,
            "title": issue.title,
            "url": issue.url,
        },
    )
    return EXIT_OK


def _description(args: argparse.Namespace) -> str:
    if args.description_file:
        path = Path(args.description_file).expanduser()
        if not path.is_file():
            raise PMError(f"Description file not found: {path}")
        return path.read_text(encoding="utf-8")
    if args.description:
        return str(args.description)
    raise PMError("Either --description or --description-file is required.")
