"""`create-issue` — create a single issue inside this repo's declared scope."""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK, PMError
from ._input import read_text_arg
from ._output import print_write_outcome
from ._wiring import prepare_write


def run(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)

    outcome = guard.create_issue(
        title=args.title,
        description=_description(args),
        project_id=args.project_id,
        state=args.state,
        priority=args.priority,
        assignee_email=args.assignee,
        labels=args.label or [],
    )
    print_write_outcome(
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
    from_file = read_text_arg(args.description_file, "Description")
    if from_file is not None:
        return from_file
    if args.description:
        return str(args.description)
    raise PMError("Either --description or --description-file is required.")
