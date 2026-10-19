from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .field_ownership import FieldOwnershipError, FieldOwnershipPolicy


@dataclass(frozen=True)
class SyncOperation:
    operation_id: str
    action: str
    source_id: str | None
    target_id: str | None
    fields: dict[str, Any]
    reason: str | None = None


@dataclass(frozen=True)
class SyncPlan:
    plan_id: str
    mapping_fingerprint: str
    source_count: int
    target_count: int
    protected_field_count: int
    legacy_unlinked_count: int
    complete: bool
    operations: tuple[SyncOperation, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {action: sum(op.action == action for op in self.operations) for action in ("CREATE", "UPDATE", "SKIP", "BLOCK")}

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "mapping_fingerprint": self.mapping_fingerprint, "source_count": self.source_count, "target_count": self.target_count, "protected_field_count": self.protected_field_count, "legacy_unlinked_count": self.legacy_unlinked_count, "complete": self.complete, "counts": self.counts, "operations": [asdict(op) for op in self.operations]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SyncPlan":
        return cls(value["plan_id"], value["mapping_fingerprint"], int(value["source_count"]), int(value["target_count"]), int(value.get("protected_field_count", 0)), int(value.get("legacy_unlinked_count", 0)), bool(value.get("complete", False)), tuple(SyncOperation(**item) for item in value["operations"]))


class SyncPlanner:
    def build_plan(self, source_records: list[dict[str, Any]], target_records: list[dict[str, Any]], mapping: FieldOwnershipPolicy, *, source_complete: bool = True, target_complete: bool = True) -> SyncPlan:
        if not source_complete or not target_complete:
            return self._blocked(source_records, target_records, mapping, "Incomplete snapshot")
        source_by_id: dict[str, dict[str, Any]] = {}
        blocks: list[SyncOperation] = []
        for source in source_records:
            source_id = source.get("_id")
            if not isinstance(source_id, str) or not source_id:
                blocks.append(self._op("BLOCK", None, None, {}, "Source record is missing string _id"))
            elif source_id in source_by_id:
                blocks.append(self._op("BLOCK", source_id, None, {}, "Duplicate source identity"))
            else:
                source_by_id[source_id] = source
        target_by_id: dict[str, dict[str, Any]] = {}
        legacy = 0
        for target in target_records:
            target_id = target.get("record_id")
            identity = mapping.field_value(target, mapping.system_fields.get("jdy_id", "jdy_id"))
            if not isinstance(target_id, str) or not target_id:
                blocks.append(self._op("BLOCK", None, None, {}, "Target record is missing record_id")); continue
            if identity in (None, ""):
                legacy += 1
                continue
            if not isinstance(identity, str):
                blocks.append(self._op("BLOCK", None, target_id, {}, "Invalid target jdy_id")); continue
            if identity in target_by_id:
                blocks.append(self._op("BLOCK", identity, target_id, {}, "Duplicate target identity"))
            else:
                target_by_id[identity] = target
        for source_id in sorted(source_by_id):
            source = source_by_id[source_id]
            target = target_by_id.get(source_id)
            if target is None:
                if legacy:
                    blocks.append(self._op("BLOCK", source_id, None, {}, "Unmatched source with legacy unlinked target records")); continue
                action = "CREATE"
            else:
                action = "UPDATE"
            fields = mapping.build_system_fields(source_id) if action == "CREATE" else {}
            fields.update(mapping.build_update_fields(source))
            if action == "UPDATE":
                changed = {key: value for key, value in fields.items() if mapping.field_value(target, key) != value}
                action = "UPDATE" if changed else "SKIP"
                fields = changed
            blocks.append(self._op(action, source_id, target.get("record_id") if target else None, fields))
        operations = tuple(sorted(blocks, key=lambda item: (item.source_id or "", item.target_id or "", item.action)))
        fingerprint = hashlib.sha256(json.dumps([asdict(item) for item in operations], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return SyncPlan(fingerprint, fingerprint, len(source_records), len(target_records), len(target_records) - legacy, legacy, True, operations)

    def _blocked(self, source_records, target_records, mapping, reason):
        op = self._op("BLOCK", None, None, {}, reason)
        return SyncPlan("blocked", "", len(source_records), len(target_records), 0, 0, False, (op,))

    @staticmethod
    def _op(action, source_id, target_id, fields, reason=None):
        raw = json.dumps([action, source_id, target_id, fields, reason], sort_keys=True, separators=(",", ":"))
        return SyncOperation(hashlib.sha256(raw.encode()).hexdigest()[:16], action, source_id, target_id, fields, reason)
