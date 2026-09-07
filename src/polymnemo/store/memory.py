"""In-memory store for local development and tests.

Keeps everything in a dict and ranks ``search`` by cosine similarity in pure
Python (no numpy dependency). Not durable and not concurrency-safe — the
durable implementation is ``PostgresStore`` (#6).

Namespaces are shared vs private (#14): reads in a *shared* namespace are
visible to every user (the "born shared" collection), while any other namespace
is private to its owner. Writes are always owner-scoped — a user can only
update/delete their own memories, even in a shared namespace.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
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
    def __init__(self, shared_namespaces: Iterable[str] = ()) -> None:
        # memory_id -> (Memory, embedding)
        self._rows: dict[str, tuple[Memory, list[float]]] = {}
        # Namespaces whose reads are visible to every user.
        self._shared: frozenset[str] = frozenset(shared_namespaces)

    def _readable(self, mem: Memory, user_id: str) -> bool:
        """Owner can always read; anyone can read a shared namespace."""
        return mem.user_id == user_id or mem.namespace in self._shared

    def add(self, memory: Memory, embedding: Sequence[float]) -> str:
        if memory.created_at is None:
            memory.created_at = utcnow()
        memory.updated_at = memory.created_at
        self._rows[memory.id] = (memory, list(embedding))
        return memory.id

    def get(self, user_id: str, memory_id: str) -> Memory | None:
        row = self._rows.get(memory_id)
        if row is None or not self._readable(row[0], user_id):
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
            if mem.namespace != namespace or not self._readable(mem, user_id):
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
            if mem.namespace == namespace and self._readable(mem, user_id)
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
            if mem.namespace == namespace and self._readable(mem, user_id)
        )

    def get_session(self, user_id: str, session_id: str) -> list[Memory]:
        rows = [
            mem
            for mem, _ in self._rows.values()
            if mem.user_id == user_id and mem.session_id == session_id
        ]
        rows.sort(key=lambda m: (m.seq if m.seq is not None else 0))
        return [self._clone(m) for m in rows]

    def delete_session(self, user_id: str, session_id: str) -> int:
        ids = [
            mid
            for mid, (mem, _) in self._rows.items()
            if mem.user_id == user_id and mem.session_id == session_id
        ]
        for mid in ids:
            del self._rows[mid]
        return len(ids)

    def replace_session(
        self,
        user_id: str,
        session_id: str,
        memories: Sequence[Memory],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        # Atomic per the Store contract: build the new rows fully, then swap.
        # If anything fails while building, the old session is left untouched;
        # the swap itself is only failure-proof dict ops (delete + update).
        now = utcnow()
        new_rows: dict[str, tuple[Memory, list[float]]] = {}
        for memory, embedding in zip(memories, embeddings):
            if memory.created_at is None:
                memory.created_at = now
            memory.updated_at = memory.created_at
            new_rows[memory.id] = (memory, list(embedding))

        stale = [
            mid
            for mid, (mem, _) in self._rows.items()
            if mem.user_id == user_id and mem.session_id == session_id
        ]
        for mid in stale:
            del self._rows[mid]
        self._rows.update(new_rows)

    @staticmethod
    def _clone(mem: Memory) -> Memory:
        # Return copies so callers can't mutate stored state (e.g. setting score).
        return replace(mem, tags=list(mem.tags))
