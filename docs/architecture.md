# P0 architecture

P0 is intentionally read-only. `Settings` loads credentials and endpoint configuration, `JiandaoyunClient` owns every HTTP call, and the CLI coordinates diagnostics. No Feishu adapter or write path exists in this phase.

Jiandaoyun remains the future synchronization source of truth. The client preserves the raw widget and record payloads, including `_id` and `_widget_*` keys, so later phases can define explicit field ownership and conversions.

Record traversal uses the API's `data_id` cursor. The cursor is the last returned record ID; the client rejects duplicate records and a cursor that does not advance. A page shorter than the requested limit terminates traversal. An empty page is a valid empty result.

Authentication, HTTP, network, JSON, platform, and pagination failures are raised rather than converted into an apparently successful empty result. Retry is limited to HTTP 429/5xx and transient transport errors; authentication errors are not retried.

P1 and later concerns—Feishu field ownership, upsert/delete behavior, persistence, webhooks, reconciliation, and deployment—are deliberately outside this package.
