"""SearchService — duplicate detection before plan mode proposes new issues."""

from __future__ import annotations

from collections.abc import Sequence

from ..models.tracker import Issue
from ..repositories.providers.base import IssueProvider


class SearchService:
    def __init__(self, provider: IssueProvider) -> None:
        self.provider = provider

    def search_issues(self, query: str, *, project_ids: Sequence[str] | None = None) -> list[Issue]:
        """Search every list in scope, not just the first.

        Missing a duplicate here is not a small error: it is how a ticket that
        already exists gets proposed and created again.
        """
        if not project_ids:
            return self.provider.search_issues(query)

        seen: set[str] = set()
        merged: list[Issue] = []
        for project_id in project_ids:
            for issue in self.provider.search_issues(query, project_id=project_id):
                if issue.identifier not in seen:
                    seen.add(issue.identifier)
                    merged.append(issue)
        return merged
