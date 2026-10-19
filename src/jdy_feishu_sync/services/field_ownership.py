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
    def __init__(self, managed_fields: list[ManagedField], system_fields: dict[str, str] | None = None):
        self.managed_fields = managed_fields
        self.system_fields = dict(system_fields or {})
        self._target_names: dict[str, str] = {}

    def validate_system_fields(self, target_fields: list[dict[str, Any]]) -> None:
        required = {"jdy_id", "jdy_deleted"}
        missing = sorted(required - self.system_fields.keys())
        if missing:
            raise FieldOwnershipError("Mapping is missing required system_fields entries: " + ", ".join(f"{name}.target_id" for name in missing))
        target_by_id = {str(item.get("field_id", "")): item for item in target_fields}
        for name, target_id in self.system_fields.items():
            if target_id not in target_by_id:
                raise FieldOwnershipError(f"Unknown system target field for {name}: {target_id}")
            field = target_by_id[target_id]
            field_name = str(field.get("field_name", ""))
            if field_name and field_name != name:
                raise FieldOwnershipError(f"System field {name} points to field named {field_name}, not {name}")
            field_type = field.get("type")
            expected = {"jdy_id": {1}, "jdy_deleted": {7}, "jdy_updated_at": {5, 20}, "synced_at": {5, 20}}[name]
            if isinstance(field_type, int) and field_type not in expected:
                labels = {1: "Text", 5: "DateTime", 7: "Checkbox", 20: "DateTime"}
                expected_label = "/".join(labels.get(item, str(item)) for item in sorted(expected))
                actual_label = str(field.get("ui_type") or labels.get(field_type, field_type))
                raise FieldOwnershipError(f"Incompatible type for system field {name}: actual {actual_label} (type={field_type}), expected {expected_label} (type={sorted(expected)})")
        if len(set(self.system_fields.values())) != len(self.system_fields):
            raise FieldOwnershipError("Duplicate target IDs in system fields")
        self._target_names = {str(item.get("field_id", "")): str(item.get("field_name", "")) for item in target_fields}

    def validate_mapping(self, source_fields: list[dict[str, Any]], target_fields: list[dict[str, Any]]) -> None:
        if self.system_fields:
            self.validate_system_fields(target_fields)
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

        collisions = set(self.system_fields.values()) & seen_target
        if collisions:
            raise FieldOwnershipError("Business mapping targets system field: " + ", ".join(sorted(collisions)))

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

    def build_system_fields(self, source_id: str, *, synced_at: int | None = None) -> dict[str, Any]:
        if "jdy_id" not in self.system_fields or "jdy_deleted" not in self.system_fields:
            raise FieldOwnershipError("Missing required system fields: jdy_id, jdy_deleted")
        result = {self.system_fields["jdy_id"]: source_id, self.system_fields["jdy_deleted"]: False}
        if synced_at is not None and "synced_at" in self.system_fields:
            result[self.system_fields["synced_at"]] = synced_at
        return result

    def field_value(self, record: dict[str, Any], target_id: str) -> Any:
        fields = record.get("fields", record)
        if not isinstance(fields, dict):
            return None
        if target_id in fields:
            return fields[target_id]
        name = self._target_names.get(target_id)
        return fields.get(name) if name else None
