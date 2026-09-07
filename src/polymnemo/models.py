"""Core domain type.

``Memory`` is the single record type. ``content`` is always plain text and is
the source of truth; the embedding is merely an index into it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Memory:
    id: str
    user_id: str
    namespace: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    # Set when this memory is a chunk of a saved session (#15): the session it
    # belongs to and its 0-based order, so a session can be reassembled exactly.
    session_id: str | None = None
    seq: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Populated only on search results (cosine similarity; higher = closer).
    score: float | None = None

    def to_public(self) -> dict:
        """Shape returned to clients — plain text plus useful metadata."""
        out: dict = {
            "id": self.id,
            "namespace": self.namespace,
            "content": self.content,
            "tags": list(self.tags),
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if self.score is not None:
            out["score"] = round(self.score, 6)
        return out
