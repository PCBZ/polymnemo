"""In-memory store for local development and tests.

Keeps everything in a dict and ranks ``search`` by cosine similarity in pure
Python (no numpy dependency). Not durable and not concurrency-safe — the
durable implementation is ``PostgresStore`` (#6).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Sequence

from ..models import Memory, utcnow


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class InMemoryStore:
    def __init__(self) -> None:
        # memory_id -> (Memory, embedding)
        self._rows: dict[str, tuple[Memory, list[float]]] = {}

    def add(self, memory: Memory, embedding: Sequence[float]) -> str:
        if memory.created_at is None:
            memory.created_at = utcnow()
        memory.updated_at = memory.created_at
        self._rows[memory.id] = (memory, list(embedding))
        return memory.id

    def get(self, user_id: str, memory_id: str) -> Memory | None:
        row = self._rows.get(memory_id)
        if row is None or row[0].user_id != user_id:
            return None
        return self._clone(row[0])

    def search(
        self,
        user_id: str,
        namespace: str,
        embedding: Sequence[float],
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        scored: list[tuple[float, Memory]] = []
        for mem, emb in self._rows.values():
            if mem.user_id != user_id or mem.namespace != namespace:
                continue
            scored.append((_cosine(embedding, emb), mem))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for score, mem in scored[offset : offset + limit]:
            clone = self._clone(mem)
            clone.score = score
            out.append(clone)
        return out

    def list(
        self,
        user_id: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        rows = [
            mem
            for mem, _ in self._rows.values()
            if mem.user_id == user_id and mem.namespace == namespace
        ]
        rows.sort(key=lambda m: (m.created_at or utcnow()), reverse=True)
        return [self._clone(m) for m in rows[offset : offset + limit]]

    def update(
        self,
        user_id: str,
        memory_id: str,
        content: str,
        embedding: Sequence[float],
    ) -> Memory | None:
        row = self._rows.get(memory_id)
        if row is None or row[0].user_id != user_id:
            return None
        mem = row[0]
        mem.content = content
        mem.updated_at = utcnow()
        self._rows[memory_id] = (mem, list(embedding))
        return self._clone(mem)

    def delete(self, user_id: str, memory_id: str) -> bool:
        row = self._rows.get(memory_id)
        if row is None or row[0].user_id != user_id:
            return False
        del self._rows[memory_id]
        return True

    def count(self, user_id: str, namespace: str) -> int:
        return sum(
            1
            for mem, _ in self._rows.values()
            if mem.user_id == user_id and mem.namespace == namespace
        )

    @staticmethod
    def _clone(mem: Memory) -> Memory:
        # Return copies so callers can't mutate stored state (e.g. setting score).
        return replace(mem, tags=list(mem.tags))
