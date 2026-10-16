from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from jdy_feishu_sync.config import Settings

logger = logging.getLogger(__name__)


class JiandaoyunError(RuntimeError):
    """Base error for API and response failures."""


class JiandaoyunHTTPError(JiandaoyunError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Jiandaoyun HTTP {status_code}: {message}")
        self.status_code = status_code


class JiandaoyunAPIError(JiandaoyunError):
    pass


class JiandaoyunClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None, *, max_retries: int = 3):
        self.settings = settings
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self.max_retries = max_retries

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "JiandaoyunClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    f"{self.settings.base_url}/{path.lstrip('/')}",
                    headers=headers,
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise JiandaoyunError(f"Network error calling {path}: {exc}") from exc
                self._backoff(attempt)
                continue
            if response.status_code in (429,) or response.status_code >= 500:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
            if response.status_code >= 400:
                raise JiandaoyunHTTPError(response.status_code, "request rejected")
            try:
                body = response.json()
            except ValueError as exc:
                raise JiandaoyunError(f"Invalid JSON response from {path}") from exc
            if not isinstance(body, dict):
                raise JiandaoyunError(f"Unexpected response shape from {path}")
            code = body.get("code")
            if code not in (None, 0, 200, "0", "200"):
                raise JiandaoyunAPIError(f"Jiandaoyun API error code={code}: {body.get('msg', body.get('message', 'unknown error'))}")
            return body
        raise AssertionError("unreachable")

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(min(0.25 * (2**attempt), 2.0))

    def list_entries(self) -> list[dict[str, Any]]:
        body = self._post("/app/entry/list", {"app_id": self.settings.app_id})
        forms = body.get("forms")
        if not isinstance(forms, list):
            raise JiandaoyunError("Response field 'forms' is not a list")
        return [item for item in forms if isinstance(item, dict)]

    def get_widgets(self, entry_id: str | None = None) -> list[dict[str, Any]]:
        body = self._post("/app/entry/widget/list", {"app_id": self.settings.app_id, "entry_id": entry_id or self.settings.entry_id})
        widgets = body.get("widgets", body.get("data", []))
        if not isinstance(widgets, list):
            raise JiandaoyunError("Response field 'widgets' is not a list")
        return [item for item in widgets if isinstance(item, dict)]

    def list_records(self, entry_id: str | None = None, limit: int = 100, data_id: str | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        payload: dict[str, Any] = {"app_id": self.settings.app_id, "entry_id": entry_id or self.settings.entry_id, "limit": limit}
        if data_id:
            payload["data_id"] = data_id
        body = self._post("/app/entry/data/list", payload)
        records = body.get("data", [])
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise JiandaoyunError("Response field 'data' is not a list of records")
        return records

    def iter_all_records(self, entry_id: str | None = None, limit: int = 100) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = self.list_records(entry_id, limit, cursor)
            if not page:
                return
            for record in page:
                record_id = record.get("_id")
                if not isinstance(record_id, str) or not record_id:
                    raise JiandaoyunError("Record is missing string '_id'")
                if record_id in seen:
                    raise JiandaoyunError(f"Pagination returned duplicate record {record_id}")
                seen.add(record_id)
                yield record
            next_cursor = page[-1].get("_id")
            if len(page) < limit:
                return
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise JiandaoyunError("Pagination cursor did not advance")
            cursor = next_cursor
