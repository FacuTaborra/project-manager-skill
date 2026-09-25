"""ClickUpProvider — adapter regressions plus workspace pinning and tags."""

from __future__ import annotations

from typing import Any

import pytest

from src.claude_pm.exceptions import ProviderError
from src.claude_pm.models.tracker import IssueDraft
from src.claude_pm.repositories.providers.clickup import ClickUpProvider, _is_done

WORKSPACE = "ws-1"


class FakeHttp:
    """Minimal HttpClient stand-in. Records GET/POST calls, replays canned JSON."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.headers = {"Authorization": "test-key"}
        self._responses = responses
        self.get_urls: list[str] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

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

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((url, payload))
        path = url.split("/api/v2/", 1)[-1].split("/api/v3/", 1)[-1]
        for key, response in self._responses.items():
            if path.startswith(key):
                return response  # type: ignore[no-any-return]
        raise AssertionError(f"Unexpected POST {url} (path={path!r})")


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
        assert provider.reachable_workspace_ids() == [WORKSPACE, "ws-2"]

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


class TestIsDone:
    def test_a_null_status_type_is_not_done(self) -> None:
        """ClickUp can return status.type: null; `.lower()` on it used to crash."""
        assert _is_done({"status": {"type": None, "status": "to do"}}) is False

    def test_a_missing_status_is_not_done(self) -> None:
        assert _is_done({}) is False

    def test_done_and_closed_types_are_done(self) -> None:
        assert _is_done({"status": {"type": "done"}}) is True
        assert _is_done({"status": {"type": "closed"}}) is True

    def test_case_is_ignored(self) -> None:
        assert _is_done({"status": {"type": "DONE"}}) is True


class TestResolveUserWorkspaceIdTypes:
    def test_a_numeric_team_id_still_matches_the_string_pin(self) -> None:
        """ClickUp's `team` endpoint can return numeric ids; the pin is always a str."""
        payload = {
            "teams": [
                {
                    "id": 12345,
                    "members": [
                        {"user": {"id": 42, "email": "dev@example.com", "username": "dev"}},
                    ],
                }
            ]
        }
        provider, _ = _provider({"team": payload}, workspace_id="12345")
        user = provider.resolve_user_by_email("dev@example.com")
        assert user is not None
        assert user.id == "42"


class TestPostThroughInjectedHttp:
    def test_post_uses_the_constructor_injected_http_client(self) -> None:
        """`_post` must not build its own HttpClient, bypassing `self._http`."""
        http = FakeHttp(
            {"list/list-9/task": {"id": "t1", "name": "T", "status": {"status": "to do"}}}
        )
        provider = ClickUpProvider("test-key", workspace_id=WORKSPACE, http=http)

        provider.create_issue(
            IssueDraft(title="T", description="D", project_id="list-9", team_id="space-1")
        )

        assert len(http.posts) == 1
        url, body = http.posts[0]
        assert url.endswith("list/list-9/task")
        assert body["name"] == "T"

    def test_post_v3_uses_the_injected_http_client_too(self) -> None:
        http = FakeHttp(
            {
                "team": _TEAM_PAYLOAD,
                "workspaces/ws-1/docs": {"doc": {"id": "d1", "title": "Doc"}},
            }
        )
        provider = ClickUpProvider("test-key", workspace_id=WORKSPACE, http=http)

        provider.create_doc("Doc")

        assert any(url.endswith("workspaces/ws-1/docs") for url, _ in http.posts)


_TASK = {
    "id": "abc",
    "name": "Title",
    "status": {"status": "open", "type": "open"},
    "list": {"id": "list-1", "name": "List"},
    "description": "plain text",
    "markdown_description": "## Markdown",
}


class TestGetIssue:
    def test_asks_for_the_markdown_description(self) -> None:
        provider, http = _provider({"task/abc": _TASK})
        provider.get_issue("abc")
        assert "include_markdown_description=true" in http.get_urls[0]

    def test_returns_the_markdown_that_was_written(self) -> None:
        provider, _ = _provider({"task/abc": _TASK})
        assert provider.get_issue("abc").description == "## Markdown"

    def test_falls_back_to_the_plain_description(self) -> None:
        task = {k: v for k, v in _TASK.items() if k != "markdown_description"}
        provider, _ = _provider({"task/abc": task})
        assert provider.get_issue("abc").description == "plain text"

    def test_asks_for_and_maps_the_subtasks(self) -> None:
        subtask = {"id": "sub", "name": "Child", "status": {"status": "open"}, "parent": "abc"}
        provider, http = _provider({"task/abc": {**_TASK, "subtasks": [subtask]}})

        issue = provider.get_issue("abc")

        assert "include_subtasks=true" in http.get_urls[0]
        assert [(s.identifier, s.parent_id) for s in issue.subtasks] == [("sub", "abc")]


def _task(task_id: str, *, parent: str | None = None) -> dict[str, Any]:
    return {"id": task_id, "name": task_id, "status": {"status": "open"}, "parent": parent}


class PagedHttp(FakeHttp):
    """Serves `list/<id>/task` one page at a time, keyed on the `page=` query param."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        super().__init__({})
        self._pages = pages

    def get_json(self, url: str) -> Any:
        self.get_urls.append(url)
        return self._pages[int(url.rsplit("page=", 1)[1])]


class TestListOpenIssues:
    def test_includes_subtasks_with_their_parent(self) -> None:
        http = PagedHttp([{"tasks": [_task("p"), _task("c", parent="p")], "last_page": True}])
        provider = ClickUpProvider("test-key", workspace_id=WORKSPACE, http=http)

        issues = provider.list_open_issues("list-1")

        assert "subtasks=true" in http.get_urls[0]
        assert [(i.identifier, i.parent_id) for i in issues] == [("p", None), ("c", "p")]

    def test_reads_every_page_until_the_last(self) -> None:
        http = PagedHttp(
            [
                {"tasks": [_task("a")], "last_page": False},
                {"tasks": [_task("b")], "last_page": True},
            ]
        )
        provider = ClickUpProvider("test-key", workspace_id=WORKSPACE, http=http)

        assert [i.identifier for i in provider.list_open_issues("list-1")] == ["a", "b"]
        assert len(http.get_urls) == 2

    def test_an_empty_page_stops_even_without_last_page(self) -> None:
        http = PagedHttp([{"tasks": [_task("a")], "last_page": False}, {"tasks": []}])
        provider = ClickUpProvider("test-key", workspace_id=WORKSPACE, http=http)

        assert [i.identifier for i in provider.list_open_issues("list-1")] == ["a"]
