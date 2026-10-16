from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Widget:
    field_id: str
    label: str
    type: str
    raw: dict[str, Any]
