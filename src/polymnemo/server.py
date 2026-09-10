"""polymnemo MCP server.

Boots a FastMCP app served over **Streamable HTTP** at ``/mcp`` and exposes the
memory tools. Tools stay thin: they pass the global rate-limit gate
(``@rate_limited``), authenticate the caller (``current_user``), delegate to
``MemoryService``, and surface validation errors as ``ToolError`` (via
``@tool_errors``). The wrappers live in ``tooling``; the running context and
service in ``app``.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from . import __version__, app
from .config import settings
from .tooling import current_user, rate_limited, tool_errors

logger = logging.getLogger("polymnemo")

mcp: FastMCP = FastMCP(
    name="polymnemo",
    version=__version__,
    instructions=(
        "Shared long-term memory across any LLM. Authenticate with a per-user "
        "bearer key; use `remember` to store and `recall` to search semantically."
    ),
)


@mcp.tool(annotations={"readOnlyHint": True})
def ping() -> dict:
    """Health / connectivity check.

    Returns server identity plus the active pluggable layers, so a client (or
    MCP Inspector) can confirm the connection and see how the server is wired.
    """
    return {
        "ok": True,
        "server": "polymnemo",
        "version": __version__,
        "layers": app.ctx.describe(),
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@tool_errors
@rate_limited(cost=2)
def remember(
    content: str,
    namespace: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
) -> dict:
    """Store a memory for later semantic recall.

    Large content is split into smaller chunks on write (one vector each), so
    this may create several ids. `namespace` groups memories (defaults to the
    shared namespace); `tags`/`source` are optional metadata.

    Returns `{ids, chunks, namespace}`.
    """
    return app.service.remember(
        current_user(), content, namespace=namespace, tags=tags, source=source
    )


@mcp.tool(annotations={"readOnlyHint": True})
@tool_errors
@rate_limited(cost=2)
def recall(
    query: str,
    namespace: str | None = None,
    limit: int = 8,
    cursor: str | None = None,
) -> dict:
    """Search memories by meaning and return the closest matches.

    Results are ranked by similarity and bounded by `limit` (default 8). Use the
    returned `next_cursor` with `has_more` to page further — you decide whether
    the results are enough. `namespace` selects the collection (defaults to the
    shared namespace).

    Returns `{items, total, has_more, next_cursor}`.
    """
    return app.service.recall(
        current_user(), query, namespace=namespace, limit=limit, cursor=cursor
    )


@mcp.tool(annotations={"readOnlyHint": True})
@tool_errors
@rate_limited(cost=1)
def list_memories(
    namespace: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """List stored memories newest-first (no search query).

    `namespace` selects the collection (defaults to the shared namespace). Page
    with `next_cursor` / `has_more`. Returns `{items, total, has_more, next_cursor}`.
    """
    return app.service.list_memories(
        current_user(), namespace=namespace, limit=limit, cursor=cursor
    )


@mcp.tool(annotations={"readOnlyHint": True})
@tool_errors
@rate_limited(cost=1)
def get_memory(id: str) -> dict:
    """Fetch a single memory by its id (from `remember`/`recall`/`list_memories`)."""
    return app.service.get_memory(current_user(), id)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
@tool_errors
@rate_limited(cost=2)
def update(id: str, content: str) -> dict:
    """Replace a memory's content (re-embeds it). Returns the updated memory."""
    return app.service.update(current_user(), id, content)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    }
)
@tool_errors
@rate_limited(cost=1)
def forget(id: str) -> dict:
    """Delete a memory by id. Returns `{id, deleted}` (deleted=false if absent)."""
    return app.service.forget(current_user(), id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@tool_errors
@rate_limited(cost=2)
def save_session(session_id: str, content: str, namespace: str | None = None) -> dict:
    """Persist a session's full content under `session_id` for later reload.

    Content is stored as ordered, losslessly-reassemblable chunks (also embedded,
    so it's searchable via `recall`). Re-saving the same `session_id` replaces it.
    Returns `{session_id, chunks, chars, namespace}`.
    """
    return app.service.save_session(
        current_user(), session_id, content, namespace=namespace
    )


@mcp.tool(annotations={"readOnlyHint": True})
@tool_errors
@rate_limited(cost=1)
def load_session(session_id: str, page: int = 0, page_size: int = 8000) -> dict:
    """Reload a saved session's content, one character page at a time.

    Page with `page` (0-based) while `has_more` is true. Returns
    `{session_id, content, page, page_size, total_chars, has_more}`.
    """
    return app.service.load_session(
        current_user(), session_id, page=page, page_size=page_size
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@tool_errors
@rate_limited(cost=2)
def create_upload(
    filename: str, content_type: str, description: str, namespace: str | None = None
) -> dict:
    """Register a file / image / video memory and get a URL to upload its bytes.

    The bytes never go through this channel: `description` is embedded so the file
    is findable via `recall`. **PUT** the raw bytes to `upload_url` sending
    `upload_headers` (the signed Content-Type). **Then call `confirm_upload`** —
    the memory stays hidden from `recall` (and the size cap is enforced) until you
    do. Media defaults to a private namespace. Returns
    `{memory_id, object_key, upload_url, upload_headers, content_type, namespace}`.
    """
    return app.service.create_upload(
        current_user(), filename, content_type, description, namespace=namespace
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@tool_errors
@rate_limited(cost=1)
def confirm_upload(id: str) -> dict:
    """Confirm a media upload after you've PUT the bytes.

    Verifies the object exists, records its real size + checksum (and rejects an
    over-limit upload), then makes the memory findable via `recall` /
    downloadable. `id` is from `create_upload`. Returns
    `{memory_id, confirmed, size_bytes, content_type}`.
    """
    return app.service.confirm_upload(current_user(), id)


@mcp.tool(annotations={"readOnlyHint": True})
@tool_errors
@rate_limited(cost=1)
def get_download_url(id: str) -> dict:
    """Get a short-lived URL to download a media memory's bytes.

    `id` is the media memory's id (from `create_upload` / `recall`). Returns
    `{memory_id, url, content_type}`.
    """
    return app.service.get_download_url(current_user(), id)


@mcp.resource("memory://{namespace}")
def namespace_collection(namespace: str) -> dict:
    """A namespace's memories, for the authenticated user, so a client can
    auto-inject the collection. Bounded like `list_memories`; page further with
    that tool. Returns `{items, total, has_more, next_cursor}`.
    """
    return app.service.list_memories(current_user(), namespace=namespace)


def main() -> None:
    """Console-script entry point: run the server over Streamable HTTP."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "Starting polymnemo MCP server at http://%s:%s%s",
        settings.host,
        settings.port,
        settings.mcp_path,
    )
    mcp.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.mcp_path,
    )


if __name__ == "__main__":
    main()
