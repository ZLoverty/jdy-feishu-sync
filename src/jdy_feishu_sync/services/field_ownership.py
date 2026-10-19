from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .field_discovery import target_type_name


RESERVED_FIELDS = {"jdy_id", "jdy_deleted", "jdy_updated_at", "synced_at"}


@dataclass(frozen=True)
class ManagedField:
    source_id: str
    target_id: str
    transform: str | None = None


class FieldOwnershipError(ValueError):
    pass


class FieldOwnershipPolicy:
    def __init__(self, managed_fields: list[ManagedField]):
        self.managed_fields = managed_fields

    def validate_mapping(self, source_fields: list[dict[str, Any]], target_fields: list[dict[str, Any]]) -> None:
        source_ids = {str(item.get("name", "")) for item in source_fields}
        target_by_id = {str(item.get("field_id", "")): item for item in target_fields}
        seen_source: set[str] = set(); seen_target: set[str] = set()
        for item in self.managed_fields:
            if item.source_id in seen_source or item.target_id in seen_target:
                raise FieldOwnershipError("Duplicate source or target field mapping")
            if item.source_id not in source_ids:
                raise FieldOwnershipError(f"Unknown source field: {item.source_id}")
            target = target_by_id.get(item.target_id)
            if target is None:
                raise FieldOwnershipError(f"Unknown target field: {item.target_id}")
            if str(target.get("field_name", "")) in RESERVED_FIELDS:
                raise FieldOwnershipError(f"Reserved target field cannot be a business mapping: {item.target_id}")
            if item.transform not in (None, "text"):
                raise FieldOwnershipError(f"Unsupported transform: {item.transform}")
            seen_source.add(item.source_id); seen_target.add(item.target_id)

    def build_update_fields(self, source_record: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in self.managed_fields:
            if item.source_id not in source_record or source_record[item.source_id] is None:
                continue
            value = source_record[item.source_id]
            if item.transform == "text" and not isinstance(value, str):
                value = str(value)
            result[item.target_id] = value
        return result
