from __future__ import annotations

from collections.abc import Sequence

from ..models.tracker import Issue
from ..repositories.providers.base import IssueProvider


class SearchService:
    def __init__(self, provider: IssueProvider) -> None:
        self.provider = provider

    def search_issues(self, query: str, *, project_ids: Sequence[str] | None = None) -> list[Issue]:
        """Every list in scope, not just the first: a missed duplicate gets created again."""
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
