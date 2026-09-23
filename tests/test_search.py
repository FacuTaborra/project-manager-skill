"""Duplicate detection across every list the repo writes to."""

from __future__ import annotations

from src.claude_pm.application.search import SearchService
from src.claude_pm.domain.models import Issue, State


class FakeProvider:
    def __init__(self, by_project: dict[str | None, list[str]]) -> None:
        self.by_project = by_project
        self.queried: list[str | None] = []

    def search_issues(self, query: str, *, project_id: str | None = None) -> list[Issue]:
        self.queried.append(project_id)
        return [
            Issue(identifier=i, title=i, state=State(id="s", name="Backlog"))
            for i in self.by_project.get(project_id, [])
        ]


def test_searches_every_list_in_scope() -> None:
    """Searching only the first list is how a duplicate gets created anyway."""
    provider = FakeProvider({"a": ["ONE"], "b": ["TWO"]})
    matches = SearchService(provider).search_projects("q", project_ids=["a", "b"])
    assert [i.identifier for i in matches] == ["ONE", "TWO"]
    assert provider.queried == ["a", "b"]


def test_an_issue_in_two_lists_appears_once() -> None:
    provider = FakeProvider({"a": ["ONE", "DUP"], "b": ["DUP", "TWO"]})
    matches = SearchService(provider).search_projects("q", project_ids=["a", "b"])
    assert [i.identifier for i in matches] == ["ONE", "DUP", "TWO"]


def test_no_project_ids_searches_the_whole_workspace() -> None:
    provider = FakeProvider({None: ["ANY"]})
    matches = SearchService(provider).search_projects("q")
    assert [i.identifier for i in matches] == ["ANY"]
    assert provider.queried == [None]


def test_an_empty_list_of_ids_is_treated_as_global() -> None:
    provider = FakeProvider({None: ["ANY"]})
    assert SearchService(provider).search_projects("q", project_ids=[])
    assert provider.queried == [None]
