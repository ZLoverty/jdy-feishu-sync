# P2 controlled synchronization

P2 adds a fail-closed planner and explicitly authorized Feishu writes. Configure required `system_fields` (`jdy_id`, `jdy_deleted`) and optionally `jdy_updated_at`/`synced_at` by real Feishu field IDs, then validate them before planning. The field IDs in `config/field_mapping.example.yaml` are placeholders and must not be used for a real write:

```bash
jdy-sync validate-system-fields
jdy-sync sync-plan --output reports/p2-plan.json
```

Planning is read-only. A plan containing `BLOCK` operations cannot be applied. This initial empty-table workflow has no adoption or historical-record migration feature. If the target is nonempty, planning uses the live `jdy_id` index and blocks duplicate or unsafe identities.

Writes require both an approved plan and `--confirm-write`:

```bash
jdy-sync sync-apply --plan reports/p2-plan.json --confirm-write
jdy-sync sync-verify
jdy-sync sync-status
```

Create uses the documented record endpoint and a deterministic UUIDv4 `client_token`; updates send only authorized field-level values. No delete operation or automatic field creation exists. The local SQLite journal records operation state, and `IN_PROGRESS`/`UNCERTAIN` entries require operator reconciliation.
