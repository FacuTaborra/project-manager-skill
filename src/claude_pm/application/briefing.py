"""BriefingService — open issues grouped by state."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..domain.binding import ScopeProject
from ..domain.models import Briefing, Issue
from ..domain.ports import IssueProvider


class BriefingService:
    def __init__(self, provider: IssueProvider) -> None:
        self.provider = provider

    def generate_per_project(
        self, *, projects: Sequence[ScopeProject], repo_name: str
    ) -> dict[str, Any]:
        sections = []
        for proj in projects:
            issues = self.provider.list_open_issues(proj.id)
            grouped: dict[str, list[Issue]] = {}
            for issue in issues:
                grouped.setdefault(issue.state.name, []).append(issue)
            sections.append(
                {
                    "project": proj.name or proj.id,
                    "project_id": proj.id,
                    "issues_by_state": grouped,
                    "total_open": len(issues),
                }
            )
        return {
            "repo": repo_name,
            "projects": sections,
        }

    def generate(self, *, project_id: str, project_name: str, repo_name: str) -> Briefing:
        issues = self.provider.list_open_issues(project_id)
        grouped: dict[str, list[Issue]] = {}
        for issue in issues:
            grouped.setdefault(issue.state.name, []).append(issue)

        return Briefing(
            repo_name=repo_name,
            project_name=project_name,
            issues_by_state=grouped,
            total_open=len(issues),
        )
