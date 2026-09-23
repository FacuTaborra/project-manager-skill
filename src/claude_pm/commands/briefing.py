"""`briefing` — open issues grouped by state, plus optional vault context."""

from __future__ import annotations

import argparse

from ..application.briefing import BriefingService
from ..application.setup_flow import SetupService
from ..exceptions import EXIT_OK, CacheInvalid
from ._helpers import (
    briefing_to_dict,
    build_context,
    get_cache_repo,
    issue_to_dict,
    prepare_read,
    print_json,
)


def run(args: argparse.Namespace) -> int:
    config, provider = prepare_read(args)
    cache = SetupService(provider, get_cache_repo(config), config).ensure()

    projects = cache.lists
    if not projects:
        raise CacheInvalid("Cache is missing list info. Run `pm setup --force`.")

    context = build_context(config)
    service = BriefingService(provider, context)

    if len(projects) > 1:
        result = service.generate_multi(projects=list(projects), repo_name=config.repo_name)
        for section in result["projects"]:
            section["issues_by_state"] = {
                state: [issue_to_dict(i) for i in issues]
                for state, issues in section["issues_by_state"].items()
            }
        print_json(result)
    else:
        briefing = service.generate(
            project_id=projects[0]["id"],
            project_name=projects[0]["name"],
            repo_name=config.repo_name,
        )
        print_json(briefing_to_dict(briefing))
    return EXIT_OK
