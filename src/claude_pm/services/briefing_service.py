from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models.repo_config import ProjectRef
from ..models.tracker import Briefing, Issue
from ..repositories.providers.base import IssueProvider


class BriefingService:
    def __init__(self, provider: IssueProvider) -> None:
        self.provider = provider

    def generate_per_project(
        self, *, projects: Sequence[ProjectRef], repo_name: str
    ) -> dict[str, Any]:
        sections = []
        for project in projects:
            issues = self.provider.list_open_issues(project.id)
            sections.append(
                {
                    "project": project.name or project.id,
                    "project_id": project.id,
                    "issues_by_state": _group_by_state(issues),
                    "total_open": len(issues),
                }
            )

        return {"repo": repo_name, "projects": sections}

    def generate(self, *, project_id: str, project_name: str, repo_name: str) -> Briefing:
        issues = self.provider.list_open_issues(project_id)

        return Briefing(
            repo_name=repo_name,
            project_name=project_name,
            issues_by_state=_group_by_state(issues),
            total_open=len(issues),
        )


def _group_by_state(issues: Sequence[Issue]) -> dict[str, list[Issue]]:
    grouped: dict[str, list[Issue]] = {}
    for issue in issues:
        grouped.setdefault(issue.state.name, []).append(issue)

    return grouped
