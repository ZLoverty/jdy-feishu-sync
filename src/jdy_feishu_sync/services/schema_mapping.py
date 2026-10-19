from __future__ import annotations

import unicodedata
from pathlib import Path
import yaml
from dataclasses import asdict, dataclass
from typing import Any

from .field_discovery import normalize_name, target_type_name


SUPPORTED_SOURCE_TYPES = {"text": 1, "textarea": 1, "number": 2, "datetime": 5, "checkbox": 7, "radiogroup": 3, "combo": 3}
RESERVED_NAMES = {"jdy_id", "jdy_deleted", "jdy_updated_at", "synced_at"}


@dataclass(frozen=True)
class SchemaProposal:
    source_id: str
    source_label: str
    source_type: str
    action: str
    target_name: str | None
    target_id: str | None
    target_type: int | None
    transform: str | None
    confidence: str
    explanation: str
    approved: bool = False

    def to_dict(self):
        return asdict(self)


def build_proposals(source_fields: list[dict[str, Any]], target_fields: list[dict[str, Any]]) -> list[SchemaProposal]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for target in target_fields:
        by_name.setdefault(normalize_name(str(target.get("field_name", ""))), []).append(target)
    proposals: list[SchemaProposal] = []
    for source in source_fields:
        source_id = str(source.get("name", "")); label = str(source.get("label", "")).strip(); source_type = str(source.get("type", ""))
        target_type = SUPPORTED_SOURCE_TYPES.get(source_type)
        if normalize_name(label) in RESERVED_NAMES:
            proposals.append(SchemaProposal(source_id, label, source_type, "IGNORE", None, None, None, None, "HIGH", "Reserved system field; configure under system_fields", False)); continue
        matches = by_name.get(normalize_name(label), [])
        if len(matches) > 1:
            proposals.append(SchemaProposal(source_id, label, source_type, "AMBIGUOUS", label, None, target_type, None, "LOW", "Multiple Feishu fields have the same normalized name", False)); continue
        if len(matches) == 1:
            target = matches[0]; actual = target.get("type")
            if target_type is not None and actual == target_type:
                proposals.append(SchemaProposal(source_id, label, source_type, "MATCH_EXISTING", label, str(target.get("field_id")), target_type, "text" if source_type in {"text", "textarea"} else None, "HIGH", "Exact normalized name and compatible type", False))
            else:
                proposals.append(SchemaProposal(source_id, label, source_type, "AMBIGUOUS", label, str(target.get("field_id")), target_type, None, "LOW", f"Existing field type {target_type_name(actual)} is incompatible with source type {source_type}", False))
            continue
        if target_type is None:
            proposals.append(SchemaProposal(source_id, label, source_type, "UNSUPPORTED", label, None, None, None, "HIGH", f"Source widget type {source_type} has no verified Feishu conversion", False))
        else:
            proposals.append(SchemaProposal(source_id, label, source_type, "CREATE_NEW", label, None, target_type, "text" if source_type in {"text", "textarea"} else None, "MEDIUM", "No exact existing field; explicit approval required", False))
    return proposals


def proposal_payload(proposals: list[SchemaProposal]) -> dict[str, Any]:
    return {"version": 1, "proposals": [item.to_dict() for item in proposals]}


def load_proposals(path: Path) -> list[SchemaProposal]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [SchemaProposal(**item) for item in payload.get("proposals", []) if isinstance(item, dict)]


def validate_proposals(proposals: list[SchemaProposal]) -> list[str]:
    errors: list[str] = []
    seen_sources: set[str] = set()
    for item in proposals:
        if item.source_id in seen_sources:
            errors.append(f"duplicate source proposal: {item.source_id}")
        seen_sources.add(item.source_id)
        if item.approved and item.action not in {"MATCH_EXISTING", "CREATE_NEW"}:
            errors.append(f"approved proposal has unsafe action: {item.source_id} ({item.action})")
        if item.action == "CREATE_NEW" and item.target_type not in set(SUPPORTED_SOURCE_TYPES.values()):
            errors.append(f"unsupported CREATE_NEW type: {item.source_id}")
    return errors
