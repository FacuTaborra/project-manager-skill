"""The board itself: list its teams, projects, states, labels and members; create projects and teams."""

from __future__ import annotations

from argparse import Namespace

from ..dependencies.provider import get_provider
from ..dependencies.repo_config import get_repo_config
from ..dependencies.scope_guard import get_scope_guard
from ..exceptions import EXIT_OK, PMError
from ._output import print_json, print_write_outcome


def list_teams(args: Namespace) -> int:
    teams = get_provider(get_repo_config(args)).list_teams()
    print_json({"teams": [{"id": t.id, "name": t.name, "key": t.key} for t in teams]})

    return EXIT_OK


def list_projects(args: Namespace) -> int:
    config = get_repo_config(args)
    projects = get_provider(config).list_projects(args.team_id or config.scope.team_id)

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


def list_states(args: Namespace) -> int:
    config = get_repo_config(args)
    states = get_provider(config).list_states(config.scope.team_id)
    print_json({"states": {s.name: s.id for s in states}})

    return EXIT_OK


def list_labels(args: Namespace) -> int:
    config = get_repo_config(args)
    labels = get_provider(config).list_labels(config.scope.team_id)
    print_json({"labels": [{"id": label.id, "name": label.name} for label in labels]})

    return EXIT_OK


def resolve_user(args: Namespace) -> int:
    user = get_provider(get_repo_config(args)).resolve_user_by_email(args.email)
    if not user:
        raise PMError(f"No member with email {args.email!r} in this workspace.")
    print_json({"user": {"id": user.id, "email": user.email, "name": user.name}})

    return EXIT_OK


def create_project(args: Namespace) -> int:
    print_write_outcome(
        get_scope_guard(args).create_project(args.name),
        lambda project: {"ok": True, "project": {"id": project.id, "name": project.name}},
    )
    return EXIT_OK


def create_team(args: Namespace) -> int:
    print_write_outcome(
        get_scope_guard(args).create_team(args.name),
        lambda team: {"ok": True, "team": {"id": team.id, "name": team.name, "key": team.key}},
    )
    return EXIT_OK
