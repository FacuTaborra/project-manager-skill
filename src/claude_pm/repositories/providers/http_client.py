from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ...exceptions import ProviderError

_DEFAULT_TIMEOUT_SECONDS = 30
_RETRY_DELAY_SECONDS = 1
_AUTH_REJECTED_CODES = (401, 403)
_SERVER_ERROR_MIN_CODE = 500
_ERROR_DETAIL_MAX_CHARS = 200
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"


class _TransientError(ProviderError):
    """Raised on 5xx and network errors so `_execute` can retry them; escapes after the last try."""


class HttpClient:
    def __init__(
        self,
        headers: dict[str, str],
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 1,
        auth_hint: str = "",
    ) -> None:
        self.headers = headers
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth_hint = auth_hint

    def get_json(self, url: str) -> Any:
        return self._execute(urllib.request.Request(url, headers=self.headers, method="GET"))

    def put_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_json("PUT", url, payload)

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_json("POST", url, payload)

    def _send_json(self, method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={**self.headers, "Content-Type": _JSON_CONTENT_TYPE},
            method=method,
        )
        result = self._execute(req)
        if not isinstance(result, dict):
            raise ProviderError(f"Unexpected response shape: {type(result).__name__}")

        return result

    def _execute(self, req: urllib.request.Request) -> Any:
        for _ in range(self.max_retries):
            try:
                return self._request(req)
            except _TransientError:
                time.sleep(_RETRY_DELAY_SECONDS)

        return self._request(req)

    def _request(self, req: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = _safe_read(e)[:_ERROR_DETAIL_MAX_CHARS]
            if e.code in _AUTH_REJECTED_CODES:
                raise ProviderError(
                    f"Authentication rejected (HTTP {e.code}). "
                    f"{self.auth_hint or 'Check your API key and scopes.'} Detail: {detail}"
                ) from e
            if e.code >= _SERVER_ERROR_MIN_CODE:
                raise _TransientError(f"HTTP {e.code}: {detail}") from e
            raise ProviderError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise _TransientError(f"Network error: {e}") from e


def _safe_read(err: urllib.error.HTTPError) -> str:
    try:
        return err.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
