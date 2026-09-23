"""Presentation shared by `pm creds add` and the `pm init` wizard: the provider
menu, where to get a token, and the confirmation printed once one is saved.
"""

from __future__ import annotations

import sys

from ..credentials import credentials_path
from ..domain.models import Team
from ..enums import ProviderType
from ._prompt import Choice, choose

WHERE_TO_GET_ONE = {
    ProviderType.CLICKUP: "ClickUp → Settings → Apps → API Token",
    ProviderType.LINEAR: "https://linear.app/settings/api (Read + Write)",
}


def ask_provider() -> ProviderType:
    picked = choose(
        "Which tracker does this repo use?",
        [Choice(id=p.value, label=p.value, detail=WHERE_TO_GET_ONE[p]) for p in ProviderType],
    )
    return ProviderType(picked[0])


def report(name: str, email: str, reachable: list[Team], workspace_id: str | None) -> None:
    print(f"  ✓ token valid — authenticated as {email}", file=sys.stderr)
    print(
        f"  ✓ reaches {len(reachable)} workspace(s): "
        + ", ".join(f"{w.name} ({w.id})" for w in reachable),
        file=sys.stderr,
    )
    if workspace_id:
        print(f"  ✓ profile pinned to {workspace_id}", file=sys.stderr)
    print(f"  ✓ profile {name!r} written to {credentials_path()}", file=sys.stderr)
