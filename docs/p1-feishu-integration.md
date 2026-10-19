# P1 Feishu read-only integration

P1 adds read-only access to a Feishu Bitable table. It does not create, update, or delete Feishu records.

Configure `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_APP_TOKEN`, and `FEISHU_TABLE_ID` in `.env`. The client obtains and caches a `tenant_access_token`; the current OAuth endpoint returns `access_token` and `expires_in`, while the client also accepts the legacy token field for compatibility.

Commands:

```bash
jdy-sync feishu-check
jdy-sync feishu-inspect-fields
jdy-sync feishu-inspect-records --limit 5
jdy-sync feishu-count-records
jdy-sync compare-fields
jdy-sync export-field-mapping --output config/field_mapping.candidates.yaml
jdy-sync validate-field-mapping --mapping config/field_mapping.yaml
jdy-sync preview-update --record-id SOURCE_RECORD_ID --mapping config/field_mapping.yaml
```

The read client resolves the configured table by paging through `GET /bitable/v1/apps/{app_token}/tables`; it never calls the invalid `GET /tables/{table_id}` metadata route. Application metadata remains available through `get_app()`. Field and record reads retain their documented table-scoped endpoints. Record traversal follows `has_more` and `page_token`, rejecting repeated tokens, duplicate record IDs, malformed responses, and business errors returned with HTTP 200. HTTP 404 responses are reported separately from Feishu business error codes.

Candidate mappings are disabled by default. Only `managed_fields` in the approved mapping file can produce a proposed update payload; `preview-update` prints field IDs only and performs no write request.
