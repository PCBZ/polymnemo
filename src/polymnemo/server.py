"""polymnemo MCP server — Phase 0 #1 skeleton.

Boots a FastMCP app and serves it over **Streamable HTTP** at ``/mcp``. The only
tool for now is ``ping`` (a connectivity check); the real memory tools
(``remember`` / ``recall`` / ...) arrive in Phase 1.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from . import __version__
from .config import settings

logger = logging.getLogger("polymnemo")

mcp: FastMCP = FastMCP(
    name="polymnemo",
    instructions=(
        "Shared long-term memory across any LLM. Skeleton build: only `ping` is "
        "available so far; memory tools land in Phase 1."
    ),
)


@mcp.tool
def ping() -> dict:
    """Health / connectivity check.

    Returns basic server identity so a client (or MCP Inspector) can confirm the
    connection. Placeholder tool for the Phase 0 skeleton.
    """
    return {"ok": True, "server": "polymnemo", "version": __version__}


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
