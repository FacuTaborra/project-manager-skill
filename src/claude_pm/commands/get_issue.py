"""`get-issue` — fetch a single issue by ID, including its description."""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._helpers import issue_to_dict, prepare_read, print_json


def run(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)

    issue = provider.get_issue(args.id)
    payload = issue_to_dict(issue, with_description=True)
    payload["id"] = issue.identifier
    print_json(payload)
    return EXIT_OK
