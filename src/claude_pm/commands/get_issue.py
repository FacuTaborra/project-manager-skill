"""`get-issue` — fetch a single issue by ID, including its description."""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._helpers import issue_to_dict, prepare_read, print_json


def run(args: argparse.Namespace) -> int:
    """`id` repeats `identifier` on purpose: it was this command's key before the
    serializers were shared, and existing callers may still read it.
    """
    _, provider = prepare_read(args)

    issue = provider.get_issue(args.id)
    payload = issue_to_dict(issue, with_description=True)
    payload["id"] = issue.identifier
    print_json(payload)
    return EXIT_OK
