"""LinearProvider — parent/children mapping for sub-issues."""

from __future__ import annotations

from typing import Any

from src.claude_pm.repositories.providers.linear import LinearProvider


class FakeHttp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.queries: list[str] = []

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.queries.append(payload["query"])
        return {"data": self._data}


def _node(identifier: str, **extra: Any) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "title": identifier,
        "state": {"id": "s", "name": "Todo"},
        **extra,
    }


def _provider(data: dict[str, Any]) -> tuple[LinearProvider, FakeHttp]:
    http = FakeHttp(data)
    return LinearProvider("lin_x", http=http), http  # type: ignore[arg-type]


def test_open_issues_carry_their_parent_identifier() -> None:
    nodes = [_node("FAC-1", parent=None), _node("FAC-2", parent={"identifier": "FAC-1"})]
    provider, http = _provider({"issues": {"nodes": nodes}})

    issues = provider.list_open_issues("proj-1")

    assert "parent { identifier }" in http.queries[0]
    assert [(i.identifier, i.parent_id) for i in issues] == [("FAC-1", None), ("FAC-2", "FAC-1")]


def test_get_issue_maps_children_as_subtasks() -> None:
    node = _node("FAC-1", description="d", children={"nodes": [_node("FAC-2")]})
    provider, http = _provider({"issues": {"nodes": [node]}})

    issue = provider.get_issue("FAC-1")

    assert "children" in http.queries[0]
    assert [s.identifier for s in issue.subtasks] == ["FAC-2"]
