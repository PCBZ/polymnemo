"""polymnemo MCP server — Phase 0 #1 skeleton.

Boots a FastMCP app and serves it over **Streamable HTTP** at ``/mcp``. The only
tool for now is ``ping`` (a connectivity check); the real memory tools
(``remember`` / ``recall`` / ...) arrive in Phase 1.
"""

from __future__ import annotations

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
        raise ToolError(f"Authentication failed: {exc}")


@mcp.tool
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
    user_id = _current_user()
    try:
        return service.remember(
            user_id, content, namespace=namespace, tags=tags, source=source
        )
    except ValueError as exc:
        raise ToolError(str(exc))


@mcp.tool(annotations={"readOnlyHint": True})
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
    user_id = _current_user()
    try:
        return service.recall(
            user_id, query, namespace=namespace, limit=limit, cursor=cursor
        )
    except ValueError as exc:
        raise ToolError(str(exc))


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
