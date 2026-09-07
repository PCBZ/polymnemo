"""Memory service — the business logic behind the MCP tools.

Sits between the tools (which handle transport/auth) and the pluggable layers
(store / embedder / retriever). Tools stay thin; this is where chunking,
embedding, and defaults live. Takes an explicit ``user_id`` so it has no
transport concerns and is easy to test.
"""

from __future__ import annotations

from .chunking import chunk_text
from .config import settings
from .context import AppContext
from .models import Memory, new_id


def _parse_offset(cursor: str | None) -> int:
    """The cursor is just the next offset as a string; missing/invalid -> 0."""
    try:
        return max(0, int(cursor)) if cursor else 0
    except (TypeError, ValueError):
        return 0


def _page(rows: list[Memory], total: int, offset: int) -> dict:
    """Shape a paginated result: bounded items + cursor metadata."""
    next_offset = offset + len(rows)
    has_more = next_offset < total
    return {
        "items": [row.to_public() for row in rows],
        "total": total,
        "has_more": has_more,
        "next_cursor": str(next_offset) if has_more else None,
    }


class MemoryService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def remember(
        self,
        user_id: str,
        content: str,
        namespace: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
    ) -> dict:
        """Chunk ``content``, embed each chunk, and persist text + vector.

        Returns the created ids (one per chunk) and the namespace used.
        """
        content = (content or "").strip()
        if not content:
            raise ValueError("content is empty")

        ns = namespace or settings.default_namespace
        chunks = chunk_text(content)
        embeddings = self.ctx.embedder.embed_documents(chunks)

        ids: list[str] = []
        for chunk, embedding in zip(chunks, embeddings):
            memory = Memory(
                id=new_id(),
                user_id=user_id,
                namespace=ns,
                content=chunk,
                tags=list(tags or []),
                source=source,
            )
            self.ctx.store.add(memory, embedding)
            ids.append(memory.id)

        return {"ids": ids, "chunks": len(ids), "namespace": ns}

    def recall(
        self,
        user_id: str,
        query: str,
        namespace: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict:
        """Semantic search: return bounded, similarity-ranked memories plus
        pagination metadata. The server ranks and bounds; the client decides
        whether the results are enough or to page further.
        """
        query = (query or "").strip()
        if not query:
            raise ValueError("query is empty")

        ns = namespace or settings.default_namespace
        limit = settings.recall_limit if limit is None else max(1, limit)
        offset = _parse_offset(cursor)

        rows = self.ctx.retriever.search(user_id, query, ns, limit, offset)
        return _page(rows, self.ctx.store.count(user_id, ns), offset)

    def list_memories(
        self,
        user_id: str,
        namespace: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict:
        """List memories newest-first (no query), same pagination shape as recall."""
        ns = namespace or settings.default_namespace
        limit = settings.list_limit if limit is None else max(1, limit)
        offset = _parse_offset(cursor)

        rows = self.ctx.store.list(user_id, ns, limit, offset)
        return _page(rows, self.ctx.store.count(user_id, ns), offset)

    def get_memory(self, user_id: str, memory_id: str) -> dict:
        """Fetch a single memory by id (raises if not found / not owned)."""
        memory = self.ctx.store.get(user_id, memory_id)
        if memory is None:
            raise ValueError(f"memory not found: {memory_id}")
        return memory.to_public()

    def update(self, user_id: str, memory_id: str, content: str) -> dict:
        """Replace a memory's content and re-embed it."""
        content = (content or "").strip()
        if not content:
            raise ValueError("content is empty")

        embedding = self.ctx.embedder.embed_documents([content])[0]
        memory = self.ctx.store.update(user_id, memory_id, content, embedding)
        if memory is None:
            raise ValueError(f"memory not found: {memory_id}")
        return memory.to_public()

    def forget(self, user_id: str, memory_id: str) -> dict:
        """Delete a memory; report whether a row was removed."""
        deleted = self.ctx.store.delete(user_id, memory_id)
        return {"id": memory_id, "deleted": deleted}
