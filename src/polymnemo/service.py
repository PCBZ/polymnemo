"""Memory service — the business logic behind the MCP tools.

Sits between the tools (which handle transport/auth) and the pluggable layers
(store / embedder / retriever). Tools stay thin; this is where chunking,
embedding, and defaults live. Takes an explicit ``user_id`` so it has no
transport concerns and is easy to test.
"""

from __future__ import annotations

from .chunking import chunk_text, chunk_verbatim
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


def _kind_from_content_type(content_type: str) -> str:
    """Coarse memory kind from a MIME type (image/* -> image, etc.)."""
    top = content_type.split("/", 1)[0].strip().lower()
    return top if top in ("image", "video", "audio") else "file"


def _safe_filename(filename: str) -> str:
    """Strip any path so the object key stays under the user's prefix."""
    return (filename or "").replace("\\", "/").split("/")[-1].strip()


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
            raise ValueError("content is empty — provide text to store.")

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
            raise ValueError("query is empty — provide a non-empty search string.")

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
            raise ValueError(
                f"no memory with id '{memory_id}' for this user — "
                "call list_memories to see valid ids."
            )
        return memory.to_public()

    def update(self, user_id: str, memory_id: str, content: str) -> dict:
        """Replace a memory's content and re-embed it."""
        content = (content or "").strip()
        if not content:
            raise ValueError("content is empty — provide text to store.")

        embedding = self.ctx.embedder.embed_documents([content])[0]
        memory = self.ctx.store.update(user_id, memory_id, content, embedding)
        if memory is None:
            raise ValueError(
                f"no memory with id '{memory_id}' for this user — "
                "call list_memories to see valid ids."
            )
        return memory.to_public()

    def forget(self, user_id: str, memory_id: str) -> dict:
        """Delete a memory; report whether a row was removed."""
        deleted = self.ctx.store.delete(user_id, memory_id)
        return {"id": memory_id, "deleted": deleted}

    def save_session(
        self, user_id: str, session_id: str, content: str, namespace: str | None = None
    ) -> dict:
        """Persist a session's content as ordered, verbatim (losslessly
        reassemblable) chunks — each embedded, so it's recall-able too. Replaces
        any existing content for the same ``session_id``.
        """
        session_id = (session_id or "").strip()
        if not session_id:
            raise ValueError("session_id is empty.")
        if not content:
            raise ValueError("content is empty — nothing to save.")

        # A session is a full verbatim transcript; default it to the PRIVATE
        # session namespace (not settings.default_namespace, which is "shared")
        # so its chunks aren't world-readable via recall / get_memory / memory://.
        ns = namespace or settings.session_namespace

        # Chunk + embed BEFORE touching the store: if embedding fails, the old
        # session is left untouched. The store then swaps old->new atomically.
        chunks = chunk_verbatim(content)
        embeddings = self.ctx.embedder.embed_documents(chunks)
        memories = [
            Memory(
                id=new_id(),
                user_id=user_id,
                namespace=ns,
                content=chunk,
                session_id=session_id,
                seq=seq,
            )
            for seq, chunk in enumerate(chunks)
        ]
        self.ctx.store.replace_session(user_id, session_id, memories, embeddings)

        return {
            "session_id": session_id,
            "chunks": len(chunks),
            "chars": len(content),
            "namespace": ns,
        }

    def load_session(
        self, user_id: str, session_id: str, page: int = 0, page_size: int = 8000
    ) -> dict:
        """Reassemble a saved session and return one character page of it.

        Chunks are verbatim and stored in ``seq`` order, so page N maps to the
        character window ``[page*page_size, +page_size)``. We walk the chunks and
        slice only the parts that overlap that window instead of joining (and
        holding) the whole transcript on every call — memory stays O(page_size).
        """
        page = max(0, page)
        page_size = max(1, page_size)
        start = page * page_size
        end = start + page_size

        rows = self.ctx.store.get_session(user_id, session_id)

        pos = 0  # running character offset across chunks
        parts: list[str] = []
        for row in rows:
            chunk_start, chunk_end = pos, pos + len(row.content)
            pos = chunk_end
            if chunk_end > start and chunk_start < end:  # overlaps the window
                lo = max(0, start - chunk_start)
                hi = min(len(row.content), end - chunk_start)
                parts.append(row.content[lo:hi])
        content = "".join(parts)

        return {
            "session_id": session_id,
            "content": content,
            "page": page,
            "page_size": page_size,
            "total_chars": pos,
            "has_more": start + len(content) < pos,
        }

    # -- media memories (#44) -------------------------------------------------
    def create_upload(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        description: str,
        namespace: str | None = None,
    ) -> dict:
        """Register a media memory and return a presigned URL to PUT the bytes to.

        The bytes never pass through MCP: we embed the text ``description`` (so the
        file is findable via ``recall``), store a pointer (``object_key``) in
        Postgres, and hand back a short-lived upload URL. The client uploads
        straight to object storage.
        """
        if self.ctx.blob_store is None:
            raise ValueError(
                "blob storage is not configured — set POLYMNEMO_BLOB_BACKEND."
            )
        filename = _safe_filename(filename)
        content_type = (content_type or "").strip()
        description = (description or "").strip()
        if not filename:
            raise ValueError("filename is empty.")
        if not content_type:
            raise ValueError("content_type is empty (e.g. image/png).")
        if not description:
            raise ValueError(
                "description is empty — it's what makes the file findable via recall."
            )

        ns = namespace or settings.default_namespace
        memory_id = new_id()
        object_key = f"{user_id}/{memory_id}/{filename}"
        embedding = self.ctx.embedder.embed_documents([description])[0]
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            namespace=ns,
            content=description,
            kind=_kind_from_content_type(content_type),
            object_key=object_key,
            content_type=content_type,
        )
        self.ctx.store.add(memory, embedding)
        upload_url = self.ctx.blob_store.presign_put(object_key, content_type)
        return {
            "memory_id": memory_id,
            "object_key": object_key,
            "upload_url": upload_url,
            "namespace": ns,
        }

    def get_download_url(self, user_id: str, memory_id: str) -> dict:
        """Return a short-lived presigned URL to GET a media memory's bytes."""
        if self.ctx.blob_store is None:
            raise ValueError(
                "blob storage is not configured — set POLYMNEMO_BLOB_BACKEND."
            )
        memory = self.ctx.store.get(user_id, memory_id)
        if memory is None:
            raise ValueError(
                f"no memory with id '{memory_id}' for this user — "
                "call list_memories to see valid ids."
            )
        if not memory.object_key:
            raise ValueError(
                f"memory '{memory_id}' is not a media memory (it has no stored file)."
            )
        url = self.ctx.blob_store.presign_get(memory.object_key)
        return {"memory_id": memory_id, "url": url, "content_type": memory.content_type}
