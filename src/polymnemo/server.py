"""polymnemo MCP server.

Boots a FastMCP app served over **Streamable HTTP** at ``/mcp`` and exposes the
memory tools (``remember`` / ``recall`` / ``list_memories`` / ``get_memory`` /
``update`` / ``forget``). Tools stay thin: they authenticate the caller, delegate
to :class:`MemoryService`, and surface validation errors as actionable
``ToolError`` messages (via ``_tool_errors``) instead of masked stack traces.
"""

from __future__ import annotations

import functools
import logging

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from . import __version__
from .auth import AuthError
from .config import settings
from .context import build_context
from .service import MemoryService

logger = logging.getLogger("polymnemo")

# The pluggable layers (Auth / Store / Retriever / Embedder), assembled once,
# and the service that the memory tools call through.
ctx = build_context()
service = MemoryService(ctx)

mcp: FastMCP = FastMCP(
    name="polymnemo",
    instructions=(
        "Shared long-term memory across any LLM. Authenticate with a per-user "
        "bearer key; use `remember` to store and `recall` to search semantically."
    ),
)


def _current_user() -> str:
    """Resolve the caller's ``user_id`` from the request's bearer key.

    Raises a ToolError (surfaced to the model) if authentication fails.
    """
    # get_http_headers() strips `authorization` by default; opt it back in.
    headers = get_http_headers(include={"authorization"})
    try:
        return ctx.auth.authenticate(headers)
    except AuthError as exc:
        raise ToolError(f"Authentication failed: {exc}") from exc


def _tool_errors(fn):
    """Map domain validation errors (``ValueError``) to ``ToolError`` so the
    model receives a clear, actionable message instead of a masked internal
    error / stack trace. ``functools.wraps`` preserves the signature FastMCP
    reads to build the tool schema.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


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
        "layers": ctx.describe(),
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_tool_errors
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
    return service.remember(
        _current_user(), content, namespace=namespace, tags=tags, source=source
    )


@mcp.tool(annotations={"readOnlyHint": True})
@_tool_errors
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
    return service.recall(
        _current_user(), query, namespace=namespace, limit=limit, cursor=cursor
    )


@mcp.tool(annotations={"readOnlyHint": True})
@_tool_errors
def list_memories(
    namespace: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """List stored memories newest-first (no search query).

    `namespace` selects the collection (defaults to the shared namespace). Page
    with `next_cursor` / `has_more`. Returns `{items, total, has_more, next_cursor}`.
    """
    return service.list_memories(
        _current_user(), namespace=namespace, limit=limit, cursor=cursor
    )


@mcp.tool(annotations={"readOnlyHint": True})
@_tool_errors
def get_memory(id: str) -> dict:
    """Fetch a single memory by its id (from `remember`/`recall`/`list_memories`)."""
    return service.get_memory(_current_user(), id)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
@_tool_errors
def update(id: str, content: str) -> dict:
    """Replace a memory's content (re-embeds it). Returns the updated memory."""
    return service.update(_current_user(), id, content)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    }
)
@_tool_errors
def forget(id: str) -> dict:
    """Delete a memory by id. Returns `{id, deleted}` (deleted=false if absent)."""
    return service.forget(_current_user(), id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
@_tool_errors
def save_session(
    session_id: str, content: str, namespace: str | None = None
) -> dict:
    """Persist a session's full content under `session_id` for later reload.

    Content is stored as ordered, losslessly-reassemblable chunks (also embedded,
    so it's searchable via `recall`). Re-saving the same `session_id` replaces it.
    Returns `{session_id, chunks, chars, namespace}`.
    """
    return service.save_session(
        _current_user(), session_id, content, namespace=namespace
    )


@mcp.tool(annotations={"readOnlyHint": True})
@_tool_errors
def load_session(session_id: str, page: int = 0, page_size: int = 8000) -> dict:
    """Reload a saved session's content, one character page at a time.

    Page with `page` (0-based) while `has_more` is true. Returns
    `{session_id, content, page, page_size, total_chars, has_more}`.
    """
    return service.load_session(
        _current_user(), session_id, page=page, page_size=page_size
    )


@mcp.resource("memory://{namespace}")
def namespace_collection(namespace: str) -> dict:
    """A namespace's memories, for the authenticated user, so a client can
    auto-inject the collection. Bounded like `list_memories`; page further with
    that tool. Returns `{items, total, has_more, next_cursor}`.
    """
    return service.list_memories(_current_user(), namespace=namespace)


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
