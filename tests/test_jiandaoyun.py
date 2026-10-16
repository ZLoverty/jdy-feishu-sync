import httpx
import pytest

from jdy_feishu_sync.adapters.jiandaoyun import JiandaoyunClient, JiandaoyunError, JiandaoyunHTTPError
from jdy_feishu_sync.config import Settings


def client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return JiandaoyunClient(Settings("secret", "app", "entry", "https://test"), http)


def test_list_entries_and_widgets():
    def handler(request):
        if request.url.path.endswith("/entry/list"):
            return httpx.Response(200, json={"forms": [{"name": "Products", "entry_id": "entry"}]})
        return httpx.Response(200, json={"widgets": [{"name": "_widget_1", "widgetName": "_widget_1", "label": "PI Code", "type": "text"}]})

    with client(handler) as api:
        assert api.list_entries()[0]["entry_id"] == "entry"
        assert api.get_widgets()[0]["label"] == "PI Code"


def test_pagination_and_empty_page():
    calls = []

    def handler(request):
        calls.append(request.read())
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [{"_id": "one"}, {"_id": "two"}]})
        return httpx.Response(200, json={"data": [{"_id": "three"}]})

    with client(handler) as api:
        records = list(api.iter_all_records(limit=2))
    assert [item["_id"] for item in records] == ["one", "two", "three"]
    assert b'"data_id":"two"' in calls[1]


def test_duplicate_page_fails():
    def handler(_):
        return httpx.Response(200, json={"data": [{"_id": "one"}]})

    with client(handler) as api:
        with pytest.raises(JiandaoyunError):
            list(api.iter_all_records(limit=1))


def test_http_auth_error_is_not_retried():
    with client(lambda _: httpx.Response(401, json={"code": 401})) as api:
        with pytest.raises(JiandaoyunHTTPError):
            api.list_entries()
