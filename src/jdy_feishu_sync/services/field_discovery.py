from __future__ import annotations

import unicodedata
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class FieldCandidate:
    source_id: str
    source_label: str
    source_type: str
    target_id: str | None
    target_name: str | None
    target_type: str | int | None
    compatibility: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def target_type_name(value: Any) -> str:
    return {1: "text", 2: "number", 3: "single_select", 4: "multi_select", 5: "date", 7: "checkbox", 11: "person", 13: "attachment", 15: "url"}.get(value, str(value).lower())


def compatibility(source_type: str, target_type: Any) -> tuple[str, str]:
    target = target_type_name(target_type)
    if source_type in {"text", "textarea"} and target == "text":
        return "compatible", "candidate"
    if source_type == "datetime" and target == "date":
        return "conversion", "manual_review"
    if source_type == "radiogroup" and target == "single_select":
        return "option_validation", "manual_review"
    if source_type == "combo" and target == "single_select":
        return "manual_review", "manual_review"
    if source_type == "user" and target == "person":
        return "manual_review", "manual_review"
    if source_type == "upload" and target == "attachment":
        return "unsupported", "manual_review"
    if source_type == "subform":
        return "unsupported", "manual_review"
    return "incompatible", "incompatible"


def compare_fields(source_fields: list[dict[str, Any]], target_fields: list[dict[str, Any]]) -> list[FieldCandidate]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for field in target_fields:
        by_name.setdefault(normalize_name(str(field.get("field_name", field.get("name", "")))), []).append(field)
    result: list[FieldCandidate] = []
    for source in source_fields:
        source_id = str(source.get("name", "")); label = str(source.get("label", "")); matches = by_name.get(normalize_name(label), [])
        if len(matches) != 1:
            result.append(FieldCandidate(source_id, label, str(source.get("type", "")), None, None, None, "ambiguous" if matches else "source_only", "ambiguous" if matches else "manual_review"))
            continue
        target = matches[0]; compatible, status = compatibility(str(source.get("type", "")), target.get("type"))
        result.append(FieldCandidate(source_id, label, str(source.get("type", "")), str(target.get("field_id", "")), str(target.get("field_name", target.get("name", ""))), target.get("type"), compatible, status))
    return result
