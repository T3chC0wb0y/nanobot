from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .domains import validate_domain


VALID_STATUSES = {"candidate", "promoted", "deprecated"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class MemoryRecord:
    id: str
    type: str
    domain: str
    title: str
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    promoted_at: str | None = None
    deprecated_at: str | None = None

    def validate(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid memory status: {self.status}")
        for field_name in ("id", "type", "domain", "title", "summary", "content"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Memory record field {field_name!r} is required")
        self.domain = validate_domain(self.domain)
        if not isinstance(self.tags, list) or not all(isinstance(tag, str) for tag in self.tags):
            raise ValueError("Memory tags must be a list of strings")
        if not isinstance(self.metadata, dict):
            raise ValueError("Memory metadata must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "created_at": self.created_at,
            "deprecated_at": self.deprecated_at,
            "domain": self.domain,
            "id": self.id,
            "metadata": self.metadata,
            "promoted_at": self.promoted_at,
            "status": self.status,
            "summary": self.summary,
            "tags": self.tags,
            "title": self.title,
            "type": self.type,
            "updated_at": self.updated_at,
        }
