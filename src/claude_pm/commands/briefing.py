"""`briefing` — open issues grouped by state."""

from __future__ import annotations

from argparse import Namespace

from ..dependencies.provider import get_provider
from ..dependencies.repo_config import get_repo_config
from ..exceptions import EXIT_OK
from ..services.briefing_service import BriefingService
from ._output import briefing_to_dict, issues_by_state_to_dict, print_json


def run(args: Namespace) -> int:
    config = get_repo_config(args)
    projects = config.scope.projects
    service = BriefingService(get_provider(config))

    if len(projects) > 1:
        result = service.generate_per_project(projects=projects, repo_name=config.repo_root.name)
        for section in result["projects"]:
            section["issues_by_state"] = issues_by_state_to_dict(section["issues_by_state"])
        print_json(result)
    else:
        briefing = service.generate(
            project_id=projects[0].id,
            project_name=projects[0].name or projects[0].id,
            repo_name=config.repo_root.name,
        )
        print_json(briefing_to_dict(briefing))

    return EXIT_OK
