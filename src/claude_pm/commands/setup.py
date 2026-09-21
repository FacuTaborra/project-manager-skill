"""`setup` — verify the declared scope against the tracker and refresh the cache."""

from __future__ import annotations

import argparse

from ..application.setup_flow import SetupService
from ..config import Config
from ..exceptions import EXIT_OK
from ._helpers import build_provider, get_cache_repo, print_json


def run(args: argparse.Namespace) -> int:
    config = Config.load(args.repo_name, profile_override=args.profile)
    provider = build_provider(config)
    cache_repo = get_cache_repo(config)

    result = SetupService(provider, cache_repo, config).verify(force=args.force)
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
                "space_id": cache.space_id,
                "space_name": cache.space_name,
                "lists": list(cache.lists),
                "state_ids": cache.state_ids,
                "labels": list(cache.labels),
                "last_refresh": cache.last_refresh,
            },
            "cache_path": str(cache_repo.path),
        }
    )
    return EXIT_OK
