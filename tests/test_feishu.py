import httpx
import pytest

import jdy_feishu_sync.cli as cli
from jdy_feishu_sync.adapters.feishu import FeishuAPIError, FeishuClient, FeishuConfigurationError, FeishuError, FeishuHTTPError
from jdy_feishu_sync.config import FeishuSettings


def make_client(handler):
    return FeishuClient(FeishuSettings("app", "secret", "base", "table", "https://feishu.test", "https://auth.test"), httpx.Client(transport=httpx.MockTransport(handler)))


def test_token_is_cached_and_fields_read():
    calls = []
    def handler(request):
        calls.append(request.url)
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"field_id": "fld", "field_name": "PI Code", "type": 1}]}})
    with make_client(handler) as client:
        assert client.list_fields()[0]["field_id"] == "fld"
        assert client.list_fields()[0]["field_id"] == "fld"
    assert sum(item.host == "auth.test" for item in calls) == 1


def test_record_pagination_and_duplicate_detection():
    def handler(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        token = request.url.params.get("page_token")
        if token is None:
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "r1"}], "has_more": True, "page_token": "next"}})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "r2"}], "has_more": False}})
    with make_client(handler) as client:
        assert [item["record_id"] for item in client.iter_all_records()] == ["r1", "r2"]


def test_get_table_uses_documented_table_list_and_paginates():
    paths = []

    def handler(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        paths.append(request.url.path)
        assert not request.url.path.endswith("/tables/table")
        if request.url.params.get("page_token") is None:
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"table_id": "other"}], "has_more": True, "page_token": "next"}})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"table_id": "table", "name": "Target"}], "has_more": False}})

    with make_client(handler) as client:
        assert client.get_table()["name"] == "Target"
    assert paths == ["/bitable/v1/apps/base/tables", "/bitable/v1/apps/base/tables"]


def test_feishu_check_never_calls_table_id_metadata_route():
    paths = []

    def handler(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        paths.append(request.url.path)
        if request.url.path.endswith("/tables"):
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"table_id": "table", "name": "Target"}], "has_more": False}})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"field_id": "fld", "field_name": "Name"}], "has_more": False}})

    client = make_client(handler)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cli, "_feishu_client", lambda: client)
    try:
        assert cli.main(["feishu-check"]) == 0
    finally:
        monkeypatch.undo()
        client.close()
    assert "/bitable/v1/apps/base/tables" in paths
    assert "/bitable/v1/apps/base/tables/table" not in paths


def test_missing_configured_table_is_a_configuration_error():
    def handler(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    with make_client(handler) as client:
        with pytest.raises(FeishuConfigurationError, match="FEISHU_TABLE_ID"):
            client.get_table()


def test_http_404_is_distinct_from_business_error():
    def not_found(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        return httpx.Response(404, json={"code": 0, "msg": "route not found"})

    with make_client(not_found) as client:
        with pytest.raises(FeishuHTTPError, match="HTTP 404: Not Found"):
            client.get_table()

    def business_error(request):
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"code": 0, "access_token": "token", "expires_in": 7200})
        return httpx.Response(200, json={"code": 1254004, "msg": "permission denied"})

    with make_client(business_error) as client:
        with pytest.raises(FeishuAPIError, match="API error 1254004"):
            client.get_table()


def test_repeated_page_token_fails():
    def handler(_):
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": True, "page_token": "same"}})
    with make_client(handler) as client:
        with pytest.raises(FeishuError):
            list(client.iter_all_records())
