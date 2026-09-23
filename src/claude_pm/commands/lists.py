"""Lookup helpers: list-teams, list-projects, list-states, list-labels, resolve-user.

Reads go straight to the provider. The two structural writes here go through the
guard, which refuses them unless --allow-structural-changes was passed.
"""

from __future__ import annotations

import argparse

from ..application.setup_flow import SetupService
from ..exceptions import EXIT_OK, PMError
from ._helpers import (
    get_cache_repo,
    prepare_read,
    prepare_write,
    print_json,
    print_result,
)


def run_list_teams(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)
    teams = provider.list_teams()
    print_json({"teams": [{"id": t.id, "name": t.name, "key": t.key} for t in teams]})
    return EXIT_OK


def run_list_states(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    cache = SetupService(provider, get_cache_repo(config), config).verify().cache
    print_json({"states": cache.state_ids})
    return EXIT_OK


def run_list_labels(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    labels = provider.list_labels(config.scope.space_id)
    print_json({"labels": [{"id": lbl.id, "name": lbl.name} for lbl in labels]})
    return EXIT_OK


def run_list_projects(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    projects = provider.list_projects(getattr(args, "team_id", None) or config.scope.space_id)
    print_json(
        {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "state": p.state,
                    "url": p.url,
                    "in_scope": p.id in config.scope.list_ids,
                }
                for p in projects
            ]
        }
    )
    return EXIT_OK


def run_create_project(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)
    print_result(
        guard.create_list(args.name),
        lambda project: {"project": {"id": project.id, "name": project.name}},
    )
    return EXIT_OK


def run_create_team(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)
    print_result(
        guard.create_space(args.name),
        lambda team: {"team": {"id": team.id, "name": team.name, "key": team.key}},
    )
    return EXIT_OK


def run_resolve_user(args: argparse.Namespace) -> int:
    _, provider = prepare_read(args)
    user = provider.resolve_user_by_email(args.email)
    if not user:
        raise PMError(f"No member with email {args.email!r} in this workspace.")
    print_json({"user": {"id": user.id, "email": user.email, "name": user.name}})
    return EXIT_OK
