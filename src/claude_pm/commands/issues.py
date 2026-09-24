"""`get-issue`, `search`, `create-issue`, `update-issue`."""

from __future__ import annotations

from argparse import Namespace

from ..dependencies.provider import get_provider
from ..dependencies.repo_config import get_repo_config
from ..dependencies.scope_guard import get_scope_guard
from ..exceptions import EXIT_OK, PMError
from ..services.search_service import SearchService
from ._input import read_text_arg
from ._output import issue_to_dict, print_json, print_write_outcome


def get(args: Namespace) -> int:
    """`id` repeats `identifier`: it was this command's key first, and callers may still read it."""
    issue = get_provider(get_repo_config(args)).get_issue(args.id)
    print_json({**issue_to_dict(issue, with_description=True), "id": issue.identifier})

    return EXIT_OK


def search(args: Namespace) -> int:
    config = get_repo_config(args)
    project_ids = None if args.global_search else [ref.id for ref in config.scope.projects]
    matches = SearchService(get_provider(config)).search_issues(args.query, project_ids=project_ids)

    print_json(
        {
            "query": args.query,
            "scope": "workspace" if args.global_search else config.scope.describe(),
            "matches": [issue_to_dict(i) for i in matches],
        }
    )
    return EXIT_OK


def create(args: Namespace) -> int:
    description = read_text_arg(args.description_file, "Description") or args.description
    if not description:
        raise PMError("Either --description or --description-file is required.")

    outcome = get_scope_guard(args).create_issue(
        title=args.title,
        description=description,
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


def update(args: Namespace) -> int:
    outcome = get_scope_guard(args).update_issue(
        issue_id=args.id,
        title=args.title,
        description=read_text_arg(args.description_file, "Description") or args.description,
        state=args.state,
        priority=args.priority,
        assignee_email=args.assignee,
    )
    print_write_outcome(
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
