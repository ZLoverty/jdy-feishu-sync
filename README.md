# jdy-feishu-sync

P0 provides a read-only Jiandaoyun API client and diagnostic CLI. P1 adds read-only Feishu Bitable metadata and record access, field discovery, and ownership validation. P2 adds fail-closed planning and explicitly authorized, journaled field-level synchronization; it does not implement webhooks, scheduling, deletion, or automatic field creation.

## Install

```bash
python -m pip install -e ".[test]"
copy .env.example .env
```

Fill `.env` with `JDY_API_KEY`, `JDY_APP_ID`, and `JDY_ENTRY_ID`. Existing environment variables take precedence over `.env`.

## Commands

```bash
jdy-sync check
jdy-sync inspect-fields
jdy-sync inspect-records --limit 5
jdy-sync count-records
jdy-sync verify
jdy-sync feishu-check
jdy-sync feishu-inspect-fields
jdy-sync feishu-inspect-records --limit 5
jdy-sync compare-fields
jdy-sync export-field-mapping --output config/field_mapping.candidates.yaml
jdy-sync validate-field-mapping
jdy-sync preview-update --record-id SOURCE_RECORD_ID
jdy-sync validate-system-fields
jdy-sync sync-plan --output reports/p2-plan.json
jdy-sync sync-apply --plan reports/p2-plan.json --confirm-write
jdy-sync sync-verify
jdy-sync sync-status
jdy-sync schema-propose --output reports/p2.5-field-mapping.proposed.yaml
jdy-sync schema-review --proposal reports/p2.5-field-mapping.proposed.yaml
```

Commands print metadata only; they do not print complete business records or credentials. `verify` performs the P0 read-only checks, including complete cursor-based record traversal.

## P0 boundaries

The Jiandaoyun API is the read-only source used by this phase. API keys are never logged. Network, HTTP, JSON, platform, authentication, and pagination failures are surfaced as errors; partial pagination results are not reported as successful.

Run automated tests with `pytest`. Tests use mocked HTTP responses and never require a real account or network.

For P1, configure `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_APP_TOKEN`, and `FEISHU_TABLE_ID` in `.env`. Candidate mappings are disabled by default, and `preview-update` never sends a write request. See [docs/p1-feishu-integration.md](docs/p1-feishu-integration.md) and [docs/field-ownership.md](docs/field-ownership.md).

For P2, configure approved system fields and review `sync-plan` before any write. See [docs/p2-initial-sync.md](docs/p2-initial-sync.md) and [docs/p2-recovery.md](docs/p2-recovery.md).

P2.5 provides read-only schema proposals and explicitly approved field provisioning. See [docs/p2.5-schema-assistance.md](docs/p2.5-schema-assistance.md). Schema provisioning never synchronizes records automatically.
