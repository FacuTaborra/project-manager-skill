from __future__ import annotations

from argparse import Namespace

from ..services.scope_guard import ScopeGuard
from .provider import get_provider
from .repo_config import get_repo_config


def get_scope_guard(args: Namespace) -> ScopeGuard:
    config = get_repo_config(args)

    return ScopeGuard(
        provider=get_provider(config),
        scope=config.scope,
        defaults=config.pm_file.defaults,
        dry_run=args.dry_run,
        allow_structural_changes=getattr(args, "allow_structural_changes", False),
    )
