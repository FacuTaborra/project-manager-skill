"""`setup` — verify the declared scope against the tracker and refresh the cache."""

from __future__ import annotations

import argparse

from ..application.repo_context import RepoContext
from ..exceptions import EXIT_OK
from ._output import print_json
from ._wiring import build_cache_refresher, build_provider


def run(args: argparse.Namespace) -> int:
    config = RepoContext.load(args.repo_name, profile_override=args.profile)
    provider = build_provider(config)

    result = build_cache_refresher(config, provider).refresh(force=args.force)
    cache = result.cache

    print_json(
        {
            "ok": True,
            "pm_file": str(config.pm_file.path),
            "profile": config.profile.name,
            "scope": config.scope.describe(),
            "refreshed": result.refreshed,
            "warnings": result.warnings,
            "cache": {
                "space_id": cache.team_id,
                "space_name": cache.team_name,
                "lists": list(cache.projects),
                "state_ids": cache.state_id_by_name,
                "labels": list(cache.labels),
                "last_refresh": cache.last_refresh,
            },
            "cache_path": str(config.cache_path),
        }
    )
    return EXIT_OK
