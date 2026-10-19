from __future__ import annotations

from typing import Any


class FeishuFieldSerializationError(ValueError):
    pass


def serialize_feishu_fields(authorized_fields_by_id: dict[str, Any], live_field_metadata: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert authorized stable field IDs into the field-name keys required by Bitable records."""
    by_id: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    for field in live_field_metadata:
        field_id = field.get("field_id")
        field_name = field.get("field_name")
        if not isinstance(field_id, str) or not field_id or not isinstance(field_name, str) or not field_name:
            raise FeishuFieldSerializationError("Feishu field metadata is missing field_id or field_name")
        if field_name in names and names[field_name] != field_id:
            raise FeishuFieldSerializationError(f"Duplicate Feishu field name: {field_name}")
        by_id[field_id] = field
        names[field_name] = field_id

    result: dict[str, Any] = {}
    for field_id, value in authorized_fields_by_id.items():
        field = by_id.get(field_id)
        if field is None:
            raise FeishuFieldSerializationError(f"Unknown or stale Feishu field ID: {field_id}")
        field_name = field["field_name"]
        if field_name in result:
            raise FeishuFieldSerializationError(f"Ambiguous Feishu field name: {field_name}")
        _validate_value(field, value)
        result[field_name] = value
    return result


def _validate_value(field: dict[str, Any], value: Any) -> None:
    field_type = field.get("type")
    if field_type == 1 and not isinstance(value, str):
        raise FeishuFieldSerializationError(f"Text field {field['field_name']} requires a string value")
    if field_type == 7 and not isinstance(value, bool):
        raise FeishuFieldSerializationError(f"Checkbox field {field['field_name']} requires a boolean value")
    if field_type in {5, 20} and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise FeishuFieldSerializationError(f"Date field {field['field_name']} requires a numeric timestamp")
    if field_type not in {1, 5, 7, 20} and isinstance(value, (dict, list)):
        raise FeishuFieldSerializationError(f"Unsupported value structure for Feishu field {field['field_name']}")
