"""Tests for HttpClient._execute: retry logic and error handling."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from src.claude_pm.exceptions import ProviderError
from src.claude_pm.infrastructure.providers._http import HttpClient


def _make_client() -> HttpClient:
    return HttpClient(headers={"Authorization": "test"}, max_retries=1)


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    body = json.dumps(data).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int, body: bytes = b"error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com",
        code=code,
        msg="err",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(body),
    )


class TestGetJson:
    def test_200_returns_parsed_json(self) -> None:
        client = _make_client()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.get_json("https://example.com/api")
        assert result == {"ok": True}

    def test_401_raises_provider_error_immediately(self) -> None:
        client = _make_client()
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            pytest.raises(ProviderError, match="Authentication rejected"),
        ):
            client.get_json("https://example.com/api")

    def test_401_carries_the_auth_hint(self) -> None:
        client = HttpClient(headers={}, auth_hint="Profile 'x' was rejected.")
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            pytest.raises(ProviderError, match="Profile 'x' was rejected"),
        ):
            client.get_json("https://example.com/api")

    def test_without_a_hint_it_keeps_the_generic_advice(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            pytest.raises(ProviderError, match="Check your API key"),
        ):
            _make_client().get_json("https://example.com/api")

    def test_403_raises_provider_error_immediately(self) -> None:
        client = _make_client()
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(403)),
            pytest.raises(ProviderError, match="Authentication rejected"),
        ):
            client.get_json("https://example.com/api")

    def test_500_retries_then_succeeds(self) -> None:
        client = _make_client()
        responses = [_http_error(500), _mock_response({"ok": True})]

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            r = responses[call_count]
            call_count += 1
            if isinstance(r, Exception):
                raise r
            return r

        with patch("urllib.request.urlopen", side_effect=side_effect), patch("time.sleep"):
            result = client.get_json("https://example.com/api")
        assert result == {"ok": True}
        assert call_count == 2

    def test_500_twice_raises_provider_error(self) -> None:
        client = _make_client()
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(500)),
            patch("time.sleep"),
            pytest.raises(ProviderError, match="HTTP 500"),
        ):
            client.get_json("https://example.com/api")

    def test_url_error_retries_then_raises(self) -> None:
        client = _make_client()
        err = urllib.error.URLError("connection refused")
        with (
            patch("urllib.request.urlopen", side_effect=err),
            patch("time.sleep"),
            pytest.raises(ProviderError, match="Network error"),
        ):
            client.get_json("https://example.com/api")


class TestPostJson:
    def test_post_returns_dict(self) -> None:
        client = _make_client()
        with patch("urllib.request.urlopen", return_value=_mock_response({"id": "123"})):
            result = client.post_json("https://example.com/api", {"title": "Test"})
        assert result == {"id": "123"}

    def test_post_non_dict_response_raises(self) -> None:
        client = _make_client()
        resp = MagicMock()
        resp.read.return_value = json.dumps([1, 2, 3]).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with (
            patch("urllib.request.urlopen", return_value=resp),
            pytest.raises(ProviderError, match="Unexpected response shape"),
        ):
            client.post_json("https://example.com/api", {"title": "Test"})
