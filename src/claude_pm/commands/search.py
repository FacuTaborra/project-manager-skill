"""`search` — duplicate detection."""

from __future__ import annotations

import argparse

from ..application.search import SearchService
from ..exceptions import EXIT_OK
from ._helpers import issue_to_dict, prepare_read, print_json


def run(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)

    project_ids = None if args.global_search else [ref.id for ref in config.scope.projects]
    matches = SearchService(provider).find_duplicates(args.query, project_ids=project_ids)

    print_json(
        {
            "query": args.query,
            "scope": "workspace" if args.global_search else config.scope.describe(),
            "matches": [issue_to_dict(i) for i in matches],
        }
    )
    return EXIT_OK
