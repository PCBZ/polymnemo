"""Structured per-call logging (#93).

One line per MCP call: what was called, by whom, how long it took, whether it
failed. Named ``observability`` rather than ``logging`` so it doesn't read like
the stdlib module.

Subclasses FastMCP's ``StructuredLoggingMiddleware`` instead of reimplementing
it. That class already measures the duration around the real call and keeps
payloads off by default, and staying on it means a library improvement arrives
for free. Three things it does that don't suit a multi-tenant server are
overridden below.

It hooks ``on_message``, the universal hook, so ``resources/read`` is covered
too. That matters: ``memory://{namespace}`` reaches the same table as the
``list_memories`` tool, but arrives as a resource read and is auto-injected by
clients rather than chosen by the model — so it can be the more frequent of the
two. A tool-only hook would leave that traffic invisible.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext

from . import app
from .auth import AuthError

logger = logging.getLogger("polymnemo")

CALL_LOGGER = "polymnemo.calls"

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(*, structured: bool, level: str) -> None:
    """Install the root log handler.

    ``force=True`` matters: ``basicConfig`` is a no-op once root has a handler,
    and by the time the entry point runs something else may already have
    installed one — which silently left our format unapplied. In json mode that
    leftover prefix (``INFO:polymnemo.calls:``) sits in front of the object and
    breaks every line's parse.

    ``level`` applies to the ``polymnemo`` logger. Root gets the *stricter* of it
    and INFO, which covers every library that leaves its own logger at NOTSET
    (SQLAlchemy, httpx, …): raising the level quietens them too, while lowering
    it to DEBUG stays ours rather than unleashing theirs.

    It does **not** reach uvicorn. Uvicorn installs levels and handlers on its
    own loggers, and does so after this runs, so its startup lines appear
    whatever ``level`` says. Measured, not assumed — they survive at ERROR.
    """
    resolved = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=max(logging.INFO, resolved),
        # In json mode the record IS the object, so nothing may precede it.
        format="%(message)s" if structured else TEXT_FORMAT,
        force=True,
    )
    logging.getLogger("polymnemo").setLevel(resolved)
    # The call log is an access log, so it gets its own level rather than
    # following `level` — the same split uvicorn draws with `uvicorn.access`.
    # Not a style preference: upstream logs failures at ERROR and successes at
    # INFO, so at WARNING the error lines survive and the success lines don't,
    # and every error-rate query reads 100% — the numerator without the
    # denominator. Partial data here is worse than none.
    logging.getLogger(CALL_LOGGER).setLevel(logging.INFO)


def _user_id() -> str | None:
    """The caller's ``user_id``, resolved exactly the way the tools resolve it.

    Goes through ``app.ctx.auth`` rather than reading the token directly, so the
    id in the log is the same string the tool wrote its memories under. Anything
    else would attribute traffic to an identity that doesn't exist.
    """
    try:
        headers = get_http_headers(include={"authorization"})
        return app.ctx.auth.authenticate(headers)
    except AuthError:
        return None  # unauthenticated call, e.g. `initialize`
    except Exception:
        # Logging must never break the request it describes.
        logger.debug("call log: could not resolve user_id", exc_info=True)
        return None


def _target(context: MiddlewareContext[Any]) -> str | None:
    """What was actually called: the tool's name, or the resource's URI.

    Upstream logs ``method``, which is only ever ``tools/call`` — useful for
    nothing per-tool. This is the field the issue's acceptance asks for, and one
    key rather than two so a single `summarize by target` covers both surfaces.
    """
    message = getattr(context, "message", None)
    name = getattr(message, "name", None)  # tools/call, prompts/get
    if name:
        return str(name)
    uri = getattr(message, "uri", None)  # resources/read
    if uri:
        return str(uri)
    return None


class CallLogMiddleware(StructuredLoggingMiddleware):
    """One structured line per call, carrying ``user_id`` and no message text."""

    def __init__(self, *, structured: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # JSON in production, `k=v` locally — the same split `log_level` uses.
        self.structured_logging = structured

    def _log_message(
        self, message: dict[str, str | int | float], log_level: int | None = None
    ) -> None:
        # One line per call, so drop the `*_start` half. Two lines double the
        # volume and make every query filter starts out.
        if str(message.get("event", "")).endswith("_start"):
            return
        super()._log_message(message, log_level)

    def _create_after_message(
        self, context: MiddlewareContext[Any], start_time: float
    ) -> dict[str, str | int | float]:
        message = super()._create_after_message(context, start_time)
        return self._annotate(message, context)

    def _create_error_message(
        self, context: MiddlewareContext[Any], start_time: float, error: Exception
    ) -> dict[str, str | int | float]:
        message = super()._create_error_message(context, start_time, error)
        # The exception's class, never its message: `tool_errors` turns domain
        # ValueErrors into ToolError with the text intact, and service-layer
        # validation echoes user input back, so `str(error)` would put caller
        # data in the logs.
        message["error"] = type(error).__name__
        return self._annotate(message, context)

    def _annotate(
        self,
        message: dict[str, str | int | float],
        context: MiddlewareContext[Any],
    ) -> dict[str, str | int | float]:
        target = _target(context)
        if target is not None:
            message["target"] = target
        user_id = _user_id()
        if user_id is not None:
            message["user_id"] = user_id
        return message
