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
        # The cursor is just the next offset as a string; missing/invalid -> 0.
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except (TypeError, ValueError):
            offset = 0

        rows = self.ctx.retriever.search(user_id, query, ns, limit, offset)
        total = self.ctx.store.count(user_id, ns)
        next_offset = offset + len(rows)
        has_more = next_offset < total

        return {
            "items": [row.to_public() for row in rows],
            "total": total,
            "has_more": has_more,
            "next_cursor": str(next_offset) if has_more else None,
        }
