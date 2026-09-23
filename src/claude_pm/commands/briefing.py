"""`briefing` — open issues grouped by state, plus optional vault context."""

from __future__ import annotations

import argparse

from ..application.briefing import BriefingService
from ..exceptions import EXIT_OK, CacheInvalid
from ._helpers import (
    briefing_to_dict,
    build_context,
    build_setup,
    issues_by_state_to_dict,
    prepare_read,
    print_json,
)


def run(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    cache = build_setup(config, provider).verify().cache

    projects = cache.lists
    if not projects:
        raise CacheInvalid("Cache is missing list info. Run `pm setup --force`.")

    context = build_context(config)
    service = BriefingService(provider, context)

    if len(projects) > 1:
        result = service.generate_multi(projects=list(projects), repo_name=config.repo_name)
        for section in result["projects"]:
            section["issues_by_state"] = issues_by_state_to_dict(section["issues_by_state"])
        print_json(result)
    else:
        briefing = service.generate(
            project_id=projects[0]["id"],
            project_name=projects[0]["name"],
            repo_name=config.repo_name,
        )
        print_json(briefing_to_dict(briefing))
    return EXIT_OK
