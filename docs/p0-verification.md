# P0 verification

The client targets `https://api.jiandaoyun.com/api/v5` by default. The following calls are implemented with `POST` and JSON bodies:

| Operation | Endpoint | Required body |
| --- | --- | --- |
| List forms | `/app/entry/list` | `app_id` |
| List widgets | `/app/entry/widget/list` | `app_id`, `entry_id` |
| List records | `/app/entry/data/list` | `app_id`, `entry_id`, `limit`, optional `data_id` |

The client sends `Authorization: Bearer <JDY_API_KEY>` and `Content-Type: application/json`. Widget display names use `label`; `name` is retained as the stable field ID. Record IDs use `_id`.

Automated tests cover configuration loading and missing credentials, form/widget parsing, record pagination, empty pages, duplicate/cursor failures, authentication failures, and CLI error exit codes. They use `httpx.MockTransport` and do not contact Jiandaoyun.

For an explicit manual integration check, configure `.env` and run `jdy-sync verify`. This performs read-only requests and should not be included in the default automated test run.
