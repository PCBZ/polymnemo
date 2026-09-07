"""Store seam — persistence for memories and their embeddings.

All access is scoped by ``user_id`` (and usually ``namespace``) so tenants stay
isolated. Vectors are stored alongside the plain-text content; ``search`` does
the vector nearest-neighbour lookup. The canonical implementation is
``PostgresStore`` (Neon + pgvector, #6); ``InMemoryStore`` covers dev/tests.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..models import Memory


@runtime_checkable
class Store(Protocol):
    def add(self, memory: Memory, embedding: Sequence[float]) -> str:
        """Persist ``memory`` with its ``embedding``; return the memory id."""
        ...

    def get(self, user_id: str, memory_id: str) -> Memory | None:
        """Fetch a single memory owned by ``user_id``, or ``None``."""
        ...

    def search(
        self,
        user_id: str,
        namespace: str,
        embedding: Sequence[float],
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        """Vector nearest-neighbour search, ranked by similarity (``score`` set).

        Results are sliced by ``offset``/``limit`` over the full ranked list so
        callers can page through them.
        """
        ...

    def list(
        self,
        user_id: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        """List memories newest-first (no query), sliced by ``offset``/``limit``."""
        ...

    def update(
        self,
        user_id: str,
        memory_id: str,
        content: str,
        embedding: Sequence[float],
    ) -> Memory | None:
        """Replace content + embedding of an existing memory; ``None`` if absent."""
        ...

    def delete(self, user_id: str, memory_id: str) -> bool:
        """Delete a memory; return whether a row was removed."""
        ...

    def count(self, user_id: str, namespace: str) -> int:
        """Total memories for ``user_id`` in ``namespace``."""
        ...

    def get_session(self, user_id: str, session_id: str) -> list[Memory]:
        """A session's chunks for ``user_id``, ordered by ``seq`` (#15)."""
        ...

    def delete_session(self, user_id: str, session_id: str) -> int:
        """Delete a session's chunks; return how many were removed."""
        ...

    def replace_session(
        self,
        user_id: str,
        session_id: str,
        memories: Sequence[Memory],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Atomically replace a session's chunks (delete old, insert new) so a
        failure can never leave the session half-written or lost."""
        ...
