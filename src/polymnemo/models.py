"""Core domain type.

``Memory`` is the single record type. ``content`` is always plain text and is
the source of truth; the embedding is merely an index into it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    # Media memories (#44): the text ``content`` is a searchable description; the
    # bytes live in object storage under ``object_key``. "text" for ordinary
    # memories (no blob).
    kind: str = "text"
    object_key: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    # Media memories start unconfirmed (bytes not uploaded yet, #50) and are
    # hidden from recall/list until confirm_upload verifies the object. Text
    # memories are born confirmed.
    confirmed: bool = True
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
        # Media memories carry a kind + content metadata; download bytes via the
        # get_download_url tool. Text memories stay unchanged (no extra keys).
        if self.kind != "text":
            out["kind"] = self.kind
            out["content_type"] = self.content_type
            out["size_bytes"] = self.size_bytes
        if self.score is not None:
            out["score"] = round(self.score, 6)
        return out
