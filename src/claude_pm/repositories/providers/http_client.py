"""Generic stdlib HTTP client for provider adapters."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ...exceptions import ProviderError


class HttpClient:
    """Minimal HTTP client built on urllib. Stateless, one per adapter.

    Supports GET, POST, PUT, PATCH JSON. Single retry on transient errors (timeouts, 5xx).
    Every method takes its url explicitly — there is no default endpoint to
    silently fall back to.
    """

    def __init__(
        self,
        headers: dict[str, str],
        timeout: int = 30,
        max_retries: int = 1,
        auth_hint: str = "",
    ) -> None:
        self.headers = headers
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth_hint = auth_hint

    def get_json(self, url: str) -> Any:
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        return self._execute(req)

    def put_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
            method="PUT",
        )
        result = self._execute(req)
        if not isinstance(result, dict):
            raise ProviderError(f"Unexpected response shape: {type(result).__name__}")
        return result

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={**self.headers, "Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        result = self._execute(req)
        if not isinstance(result, dict):
            raise ProviderError(f"Unexpected response shape: {type(result).__name__}")
        return result

    def _execute(self, req: urllib.request.Request) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                detail = _safe_read(e)
                if e.code in (401, 403):
                    raise ProviderError(
                        f"Authentication rejected (HTTP {e.code}). "
                        f"{self.auth_hint or 'Check your API key and scopes.'} Detail: {detail[:200]}"
                    ) from e
                if e.code >= 500 and attempt < self.max_retries:
                    last_err = e
                    time.sleep(1)
                    continue
                raise ProviderError(f"HTTP {e.code}: {detail[:200]}") from e
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    last_err = e
                    time.sleep(1)
                    continue
                raise ProviderError(f"Network error: {e}") from e
        raise ProviderError(f"Request failed after retries: {last_err}")


def _safe_read(err: urllib.error.HTTPError) -> str:
    try:
        return err.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
