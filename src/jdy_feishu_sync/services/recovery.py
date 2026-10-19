from __future__ import annotations

from typing import Any

from .feishu_fields import serialize_feishu_fields


def diagnose_create(client, journal, plan_id: str, source_id: str, identity_field_id: str, expected_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    row = journal.operation(plan_id, source_id)
    if row is None:
        return {"source_id": source_id, "journal_state": "NOT_FOUND", "recommended_action": "BLOCKED: operation not found"}
    metadata = client.list_fields()
    identity_name = next((field.get("field_name") for field in metadata if field.get("field_id") == identity_field_id), None)
    records = list(client.iter_all_records())
    matching_records = [record for record in records if identity_name and isinstance(record.get("fields"), dict) and record["fields"].get(identity_name) == source_id]
    matches = [record.get("record_id") for record in matching_records]
    verified = False
    if len(matching_records) == 1:
        if expected_fields is None:
            verified = True
        else:
            serialized = serialize_feishu_fields(expected_fields, metadata)
            verified = all(matching_records[0]["fields"].get(key) == value for key, value in serialized.items())
    return {
        "plan_id": row[0], "operation_id": row[1], "source_id": row[2], "action": row[4],
        "journal_state": row[6], "error_category": row[7], "client_token": row[8],
        "operation_attempts": row[5], "target_match_count": len(matches), "target_record_ids": matches,
        "record_verified": verified,
        "http_attempts": None, "last_http_result": "not persisted by current journal schema",
        "recommended_action": _recommend(row[6], len(matches), verified), "human_approval_required": True,
    }


def _recommend(state: str, matches: int, verified: bool = False) -> str:
    if matches > 1:
        return "BLOCKED: multiple exact jdy_id matches; investigate manually"
    if matches == 1:
        return "RECONCILE: record verified; explicit journal recovery authorization required" if verified else "BLOCKED: exact record exists but field verification failed"
    if state == "BLOCKED":
        return "BLOCKED: no exact target match; do not rotate token or replay CREATE"
    return "UNCERTAIN: no exact target match; operator investigation required"
