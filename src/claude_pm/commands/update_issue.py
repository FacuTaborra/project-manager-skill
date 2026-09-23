"""`update-issue` — update an issue, but only one this repo is allowed to touch."""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._helpers import prepare_write, print_result, read_text_arg


def run(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)

    description = (
        read_text_arg(args.description_file, "Description")
        if args.description_file
        else args.description
    )
    outcome = guard.update_issue(
        issue_id=args.id,
        title=args.title,
        description=description,
        state=args.state,
        priority=args.priority,
        assignee_email=args.assignee,
    )
    print_result(
        outcome,
        lambda issue: {
            "ok": True,
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state.name,
            "url": issue.url,
        },
    )
    return EXIT_OK
