from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from jdy_feishu_sync.config import FeishuSettings


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


class FeishuError(RuntimeError):
    """Base error for Feishu authentication, API, and response failures."""


class FeishuHTTPError(FeishuError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Feishu HTTP {status_code}: {message}")
        self.status_code = status_code


class FeishuRepeatedRequestError(FeishuHTTPError):
    """Feishu rejected a replayed request carrying an already-used token."""

    category = "repeated_request"


class FeishuAPIError(FeishuError):
    def __init__(self, code: int | str, message: str):
        super().__init__(f"Feishu API error {code}: {message}")
        self.code = code


class FeishuConfigurationError(FeishuError):
    """The configured Feishu resource cannot be found or is invalid."""


class FeishuClient:
    def __init__(self, settings: FeishuSettings, http_client: httpx.Client | None = None, *, max_retries: int = 3):
        self.settings = settings
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self.max_retries = max_retries
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "FeishuClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_tenant_access_token(self) -> str:
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            try:
                response = self._client.post(
                    self.settings.auth_url,
                    json={"grant_type": "client_credentials", "client_id": self.settings.app_id, "client_secret": self.settings.app_secret},
                    headers={"Content-Type": "application/json"},
                    timeout=self.settings.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise FeishuError(f"Network error during Feishu authentication: {exc}") from exc
            if response.status_code >= 400:
                raise FeishuHTTPError(response.status_code, "authentication request rejected")
            body = self._json(response, "authentication")
            if body.get("code", 0) not in (0, "0"):
                raise FeishuAPIError(body.get("code"), body.get("msg", "authentication failed"))
            token = body.get("access_token") or body.get("tenant_access_token")
            expires_in = body.get("expires_in") or body.get("expire")
            if not isinstance(token, str) or not token or not isinstance(expires_in, (int, float)):
                raise FeishuError("Feishu authentication response is missing access token or expiry")
            self._token = token
            self._token_expires_at = time.monotonic() + max(float(expires_in) - 60, 1)
            return token

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise FeishuError(f"Invalid JSON response from Feishu {operation}") from exc
        if not isinstance(body, dict):
            raise FeishuError(f"Unexpected response shape from Feishu {operation}")
        return body

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, retry: bool = True) -> dict[str, Any]:
        # CREATE is POST and must never be retried by this generic transport.
        # Its recovery is handled by the journal and exact jdy_id lookup.
        retry_allowed = retry and method.upper() in {"GET", "PUT", "PATCH", "DELETE"}
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    f"{self.settings.base_url}/{path.lstrip('/')}",
                    params=params,
                    headers={"Authorization": f"Bearer {self.get_tenant_access_token()}", "Content-Type": "application/json; charset=utf-8"},
                    timeout=self.settings.timeout_seconds,
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                if not retry_allowed or attempt >= self.max_retries:
                    raise FeishuError(f"Network error calling Feishu {path}: {exc}") from exc
                time.sleep(min(0.25 * (2**attempt), 2.0))
                continue
            if retry_allowed and response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                time.sleep(min(0.25 * (2**attempt), 2.0))
                continue
            if response.status_code >= 400:
                try:
                    detail_body = response.json()
                    detail = detail_body.get("msg", detail_body.get("message", "request rejected")) if isinstance(detail_body, dict) else "request rejected"
                except ValueError:
                    detail = "request rejected"
                if response.status_code == 404:
                    detail = f"Not Found: {detail}"
                if response.status_code == 403 and "repeated" in str(detail).lower():
                    raise FeishuRepeatedRequestError(response.status_code, str(detail))
                raise FeishuHTTPError(response.status_code, str(detail))
            body = self._json(response, path)
            if body.get("code", 0) not in (0, "0"):
                raise FeishuAPIError(body.get("code"), body.get("msg", "request failed"))
            data = body.get("data", {})
            if not isinstance(data, dict):
                raise FeishuError(f"Feishu response data is not an object for {path}")
            return data
        raise AssertionError("unreachable")

    def get_table(self) -> dict[str, Any]:
        """Find the configured table through the documented table collection endpoint."""
        token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if token:
                params["page_token"] = token
            data = self._request("GET", f"bitable/v1/apps/{self.settings.app_token}/tables", params=params)
            items = data.get("items", [])
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise FeishuError("Feishu table-list response is not a list")
            for table in items:
                if table.get("table_id") == self.settings.table_id:
                    return table
            if not data.get("has_more", False):
                raise FeishuConfigurationError(
                    f"Configured FEISHU_TABLE_ID '{self.settings.table_id}' was not found in Feishu app '{self.settings.app_token}'"
                )
            next_token = data.get("page_token")
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise FeishuError("Feishu table pagination token did not advance")
            seen_tokens.add(next_token)
            token = next_token

    def get_app(self) -> dict[str, Any]:
        """Return Bitable application metadata without accessing a table."""
        return self._request("GET", f"bitable/v1/apps/{self.settings.app_token}")

    def create_record(self, fields: dict[str, Any], *, client_token: str | None = None) -> dict[str, Any]:
        """Create only the supplied fields; client_token makes retries idempotent."""
        token = client_token or str(uuid.uuid4())
        if not _is_uuid4(token):
            raise ValueError("client_token must be a UUIDv4")
        data = self._request("POST", f"bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/records", params={"client_token": token}, json_body={"fields": fields})
        record = data.get("record", data)
        if not isinstance(record, dict):
            raise FeishuError("Feishu create response does not contain a record")
        return record

    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if not record_id:
            raise ValueError("record_id must not be empty")
        data = self._request("PUT", f"bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/records/{record_id}", json_body={"fields": fields})
        record = data.get("record", data)
        if not isinstance(record, dict):
            raise FeishuError("Feishu update response does not contain a record")
        return record

    def create_field(self, field_name: str, field_type: int, property: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create one approved Bitable field; callers must perform schema preflight."""
        if not field_name.strip():
            raise ValueError("field_name must not be empty")
        data = self._request("POST", f"bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/fields", json_body={"field_name": field_name, "type": field_type, "property": property or {}})
        field = data.get("field", data)
        if not isinstance(field, dict):
            raise FeishuError("Feishu create-field response does not contain a field")
        return field

    def list_fields(self) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if token:
                params["page_token"] = token
            data = self._request("GET", f"bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/fields", params=params)
            page = data.get("items", [])
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise FeishuError("Feishu fields response is not a list")
            fields.extend(page)
            if not data.get("has_more", False):
                return fields
            next_token = data.get("page_token")
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise FeishuError("Feishu field pagination token did not advance")
            seen_tokens.add(next_token)
            token = next_token

    def list_records(self, page_size: int = 100, page_token: str | None = None) -> dict[str, Any]:
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be between 1 and 500")
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        data = self._request("GET", f"bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/records", params=params)
        items = data.get("items", [])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise FeishuError("Feishu records response is not a list")
        return {"items": items, "page_token": data.get("page_token"), "has_more": bool(data.get("has_more", False))}

    def iter_all_records(self, page_size: int = 100) -> Iterator[dict[str, Any]]:
        token: str | None = None
        seen_tokens: set[str] = set()
        seen_records: set[str] = set()
        while True:
            page = self.list_records(page_size, token)
            for record in page["items"]:
                record_id = record.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise FeishuError("Feishu record is missing record_id")
                if record_id in seen_records:
                    raise FeishuError(f"Feishu pagination returned duplicate record {record_id}")
                seen_records.add(record_id)
                yield record
            if not page["has_more"]:
                return
            next_token = page["page_token"]
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise FeishuError("Feishu pagination token did not advance")
            seen_tokens.add(next_token)
            token = next_token
