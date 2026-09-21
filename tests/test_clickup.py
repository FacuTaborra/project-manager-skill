"""ClickUpProvider — adapter regressions plus workspace pinning and tags."""

from __future__ import annotations

from typing import Any

import pytest

from src.claude_pm.domain.models import IssueDraft
from src.claude_pm.exceptions import ProviderError
from src.claude_pm.infrastructure.providers.clickup import ClickUpProvider

WORKSPACE = "ws-1"


class FakeHttp:
    """Minimal HttpClient stand-in. Records GET URLs, replays canned JSON."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.headers = {"Authorization": "test-key"}
        self._responses = responses
        self.get_urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.get_urls.append(url)
        # Match on the path (query string ignored) using the most specific
        # (longest) registered key that it starts with.
        path = url.split("/api/v2/", 1)[-1].split("?", 1)[0]
        best: str | None = None
        for key in self._responses:
            if path.startswith(key) and (best is None or len(key) > len(best)):
                best = key
        if best is None:
            raise AssertionError(f"Unexpected GET {url} (path={path!r})")
        return self._responses[best]


_TEAM_PAYLOAD = {
    "teams": [
        {
            "id": WORKSPACE,
            "name": "Workspace",
            "members": [
                {"user": {"id": 42, "email": "dev@example.com", "username": "dev"}},
            ],
        },
        {"id": "ws-2", "name": "Other workspace", "members": []},
    ]
}


def _provider(responses: dict[str, Any], *, workspace_id: str | None = WORKSPACE):
    http = FakeHttp(responses)
    return ClickUpProvider("test-key", workspace_id=workspace_id, http=http), http


class TestWorkspacePinning:
    def test_uses_the_pinned_workspace_not_the_first_one(self) -> None:
        """`teams[0]` used to decide the board; now config does."""
        provider, http = _provider(
            {"team": _TEAM_PAYLOAD, "team/ws-2/task": {"tasks": []}}, workspace_id="ws-2"
        )
        provider.search_issues("anything")
        assert any("team/ws-2/task" in url for url in http.get_urls)

    def test_without_a_pin_it_refuses_rather_than_guessing(self) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD}, workspace_id=None)
        with pytest.raises(ProviderError, match="pm init"):
            provider.search_issues("anything")

    def test_workspace_ids_lists_everything_the_token_reaches(self) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        assert provider.workspace_ids() == [WORKSPACE, "ws-2"]

    def test_list_workspaces_carries_names_for_pm_init(self) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        assert [(w.id, w.name) for w in provider.list_workspaces()] == [
            (WORKSPACE, "Workspace"),
            ("ws-2", "Other workspace"),
        ]


class TestSearch:
    def test_url_encodes_query_with_spaces(self) -> None:
        provider, http = _provider({"team": _TEAM_PAYLOAD, "team/ws-1/task": {"tasks": []}})
        provider.search_issues("labels detail strategies alertas")
        url = next(u for u in http.get_urls if "task?query=" in u)
        assert " " not in url
        assert "labels%20detail%20strategies%20alertas" in url

    def test_url_encodes_project_id(self) -> None:
        provider, http = _provider({"team": _TEAM_PAYLOAD, "team/ws-1/task": {"tasks": []}})
        provider.search_issues("foo bar", project_id="901 713")
        url = next(u for u in http.get_urls if "task?query=" in u)
        assert "list_ids[]=901%20713" in url


class TestResolveUser:
    def test_reads_members_from_the_team_endpoint(self) -> None:
        provider, http = _provider({"team": _TEAM_PAYLOAD})
        user = provider.resolve_user_by_email("dev@example.com")
        assert user is not None
        assert user.id == "42"
        # Must not hit the non-existent team/{id}/member endpoint.
        assert not any("/member" in u for u in http.get_urls)

    def test_returns_none_when_absent(self) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        assert provider.resolve_user_by_email("nobody@example.com") is None

    def test_ignores_members_of_other_workspaces(self) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD}, workspace_id="ws-2")
        assert provider.resolve_user_by_email("dev@example.com") is None


class TestStates:
    def test_uses_status_name_as_id(self) -> None:
        provider, _ = _provider(
            {
                "space/space-1/list": {"lists": [{"id": "list-1", "name": "L"}]},
                "space/space-1/folder": {"folders": []},
                "list/list-1": {
                    "statuses": [
                        {"id": "p9_jVbTJxAI", "status": "to do"},
                        {"id": "p9_xyz", "status": "complete"},
                    ]
                },
            }
        )
        assert [(s.id, s.name) for s in provider.list_states("space-1")] == [
            ("to do", "to do"),
            ("complete", "complete"),
        ]


class TestTags:
    """ClickUp tags are space-level and identified by name, not by an id."""

    def test_list_labels_reads_space_tags(self) -> None:
        provider, http = _provider(
            {"space/space-1/tag": {"tags": [{"name": "alerts-api", "tag_bg": "#fff"}]}}
        )
        labels = provider.list_labels("space-1")
        assert [(lbl.id, lbl.name) for lbl in labels] == [("alerts-api", "alerts-api")]
        assert any("space/space-1/tag" in u for u in http.get_urls)

    def test_empty_space_has_no_labels(self) -> None:
        provider, _ = _provider({"space/space-1/tag": {}})
        assert provider.list_labels("space-1") == []

    def test_create_issue_sends_tag_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        monkeypatch.setattr(
            provider,
            "_post",
            lambda path, body: (
                captured.update(path=path, body=body)
                or {"id": "t1", "name": "T", "status": {"status": "to do"}}
            ),
        )

        provider.create_issue(
            IssueDraft(
                title="T",
                description="D",
                project_id="list-9",
                team_id="space-1",
                label_ids=("alerts-api", "energy"),
            )
        )

        assert captured["path"] == "list/list-9/task"
        assert captured["body"]["tags"] == ["alerts-api", "energy"]

    def test_create_issue_omits_tags_when_there_are_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        monkeypatch.setattr(
            provider,
            "_post",
            lambda path, body: (
                captured.update(body=body)
                or {"id": "t1", "name": "T", "status": {"status": "to do"}}
            ),
        )

        provider.create_issue(
            IssueDraft(title="T", description="D", project_id="list-9", team_id="space-1")
        )

        assert "tags" not in captured["body"]


class TestAssignee:
    def test_non_numeric_member_id_is_a_provider_error_not_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider, _ = _provider({"team": _TEAM_PAYLOAD})
        monkeypatch.setattr(provider, "_post", lambda path, body: {})

        with pytest.raises(ProviderError, match="numeric"):
            provider.create_issue(
                IssueDraft(
                    title="T",
                    description="D",
                    project_id="list-9",
                    team_id="space-1",
                    assignee_id="not-a-number",
                )
            )
