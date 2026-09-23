"""Structural writes: create-project, create-team.

Off by default — these go through the guard, which refuses them unless
--allow-structural-changes was passed.
"""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._output import print_write_outcome
from ._wiring import prepare_write


def run_create_project(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)
    print_write_outcome(
        guard.create_project(args.name),
        lambda project: {
            "ok": True,
            "project": {"id": project.id, "name": project.name},
        },
    )
    return EXIT_OK


def run_create_team(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)
    print_write_outcome(
        guard.create_team(args.name),
        lambda team: {
            "ok": True,
            "team": {"id": team.id, "name": team.name, "key": team.key},
        },
    )
    return EXIT_OK
