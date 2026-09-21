"""`get-issue` — fetch a single issue by ID, including its description."""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._helpers import prepare_read, print_json


def run(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)

    issue = provider.get_issue(args.id)
    print_json(
        {
            "id": issue.identifier,
            "title": issue.title,
            "description": issue.description,
            "state": {"id": issue.state.id, "name": issue.state.name},
            "priority": issue.priority,
            "url": issue.url,
            "project": (
                {"id": issue.project.id, "name": issue.project.name} if issue.project else None
            ),
        }
    )
    return EXIT_OK
