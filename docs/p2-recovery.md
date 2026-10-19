# P2 recovery

If execution stops, do not rerun a plan blindly. First inspect:

```bash
jdy-sync sync-status
```

An incomplete or uncertain operation must be reconciled against the live table by exact `jdy_id`. A successful remote create is treated as existing rather than blindly creating a second row; unresolved outcomes remain visible in the journal and require operator review. The local execution lock protects only processes on the same machine; it does not provide distributed locking.

For CREATE operations, the journal persists one UUIDv4 `client_token` before the request is sent. A retry or restart reuses that token for the same logical operation. Plan fingerprints and operation IDs are never sent as `client_token`, and UPDATE requests do not include the CREATE-only parameter. Token reuse does not by itself establish exactly-once semantics unless the provider confirms idempotency for the endpoint; exact `jdy_id` re-reading remains required after an uncertain result.

Interrupted CREATE diagnosis is read-only by default:

```bash
jdy-sync sync-recover --plan-id PLAN_ID --source-id SOURCE_ID
```

It never rotates a token or marks a zero-match operation successful. Recovery requires exactly one live record with the expected `jdy_id` and verified fields; otherwise the operation remains unresolved.
