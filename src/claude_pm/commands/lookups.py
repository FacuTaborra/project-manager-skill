"""Lookup helpers: list-teams, list-projects, list-states, list-labels, resolve-user.

Reads go straight to the provider.
"""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK, PMError
from ._output import print_json
from ._wiring import build_cache_refresher, prepare_read


def run_list_teams(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)
    teams = provider.list_teams()
    print_json({"teams": [{"id": t.id, "name": t.name, "key": t.key} for t in teams]})
    return EXIT_OK


def run_list_states(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    cache = build_cache_refresher(config, provider).refresh().cache
    print_json({"states": cache.state_id_by_name})
    return EXIT_OK


def run_list_labels(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    labels = provider.list_labels(config.scope.team_id)
    print_json({"labels": [{"id": lbl.id, "name": lbl.name} for lbl in labels]})
    return EXIT_OK


def run_list_projects(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    projects = provider.list_projects(getattr(args, "team_id", None) or config.scope.team_id)
    print_json(
        {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "state": p.status_text,
                    "url": p.url,
                    "in_scope": p.id in config.scope.project_ids,
                }
                for p in projects
            ]
        }
    )
    return EXIT_OK


def run_resolve_user(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)
    user = provider.resolve_user_by_email(args.email)
    if not user:
        raise PMError(f"No member with email {args.email!r} in this workspace.")
    print_json({"user": {"id": user.id, "email": user.email, "name": user.name}})
    return EXIT_OK
