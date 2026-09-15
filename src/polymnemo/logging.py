"""Logging setup, and one line per MCP call (#93).

A thin wrapper over the stdlib and over FastMCP's own logging middleware — it
configures the root handler and adds the caller's identity to each call line.
Nothing more: no metrics, no tracing.

It has no dependency on auth: the identity resolver is injected by the
composition root, the way every other layer in this project is wired.

``import logging`` inside this package still resolves to the standard library
(Python 3 imports are absolute), so the name collides only for a reader.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext

logger = logging.getLogger("polymnemo")

CALL_LOGGER = "polymnemo.calls"

# Rejected credentials are a security record, not chatter. A 401 is raised at
# the transport layer, before any middleware, so the call log cannot see it —
# this logger is the only trace, and `log_level` must not be able to hide it.
AUTH_LOGGER = "polymnemo.auth"

# A call that never returns emits no completion line, so without this it leaves
# no trace at all. Long enough that a healthy slow call (a cold embedding model
# takes ~2 s) doesn't trip it.
SLOW_CALL_SECONDS = 10.0

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(*, structured: bool, level: str) -> None:
    """Install the root handler. Called from the entry point, never on import."""
    resolved = getattr(logging, level.upper(), logging.INFO)
    # `getattr` finds any attribute of that name, not only level constants:
    # POLYMNEMO_LOG_LEVEL=BASIC_FORMAT yields a string, and the max() below
    # would raise TypeError before a single line is logged.
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        # In json mode the record IS the object, so nothing may precede it.
        format="%(message)s" if structured else TEXT_FORMAT,
        # Root gets the stricter of the two, so raising `level` also quietens
        # libraries that inherit root, while DEBUG stays ours. Does not reach
        # uvicorn, which configures its own loggers after this runs.
        level=max(logging.INFO, resolved),
        # basicConfig is a no-op once root has a handler, and by now something
        # else has installed one — without this the format is silently ignored.
        #
        # Side effect for whoever adds an observability SDK later: this removes
        # and closes EVERY existing root handler. A sentry-sdk / OpenTelemetry /
        # Azure Monitor handler registered at import time would be evicted here
        # and its capture would go dark silently. Attach such handlers after
        # this runs, or to a named logger rather than root.
        force=True,
    )
    logging.getLogger("polymnemo").setLevel(resolved)
    # The call log is an access log, so it keeps its own level. Upstream logs
    # failures at ERROR and successes at INFO, so following `level` would mean
    # WARNING drops the successes and every error-rate query reads 100%.
    logging.getLogger(CALL_LOGGER).setLevel(logging.INFO)
    # Never above WARNING: LOG_LEVEL=ERROR would otherwise silence every 401,
    # including a credential-stuffing run. Lowering it still works.
    logging.getLogger(AUTH_LOGGER).setLevel(min(resolved, logging.WARNING))


def _target(context: MiddlewareContext[Any]) -> str | None:
    """The tool's name, or the resource's URI. Upstream only logs ``method``,
    which is always ``tools/call`` and so answers nothing per-tool."""
    message = getattr(context, "message", None)
    # `is not None`, not truthiness: an empty name is an anomaly worth seeing in
    # the log, not a reason to fall through and drop `target` entirely.
    name = getattr(message, "name", None)  # tools/call, prompts/get
    if name is not None:
        return str(name)
    uri = getattr(message, "uri", None)  # resources/read
    if uri is not None:
        return str(uri)
    return None


class CallLogMiddleware(StructuredLoggingMiddleware):
    """One line per call, carrying ``user_id`` and no message text.

    Subclasses rather than reimplements: upstream already measures the duration
    around the real call and keeps payloads off. Hooks ``on_message``, so
    ``resources/read`` is covered too — ``memory://{namespace}`` reaches the
    same table as ``list_memories`` but arrives as a resource read.
    """

    def __init__(
        self,
        *,
        structured: bool = True,
        user_id: Callable[[], str | None] | None = None,
        new_scope: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        """``user_id`` and ``new_scope`` are injected by the composition root.

        This module knows nothing about auth: it starts a request scope, then
        asks whatever it was given who the caller turned out to be. Resolving
        identity here instead would mean re-running authentication on every
        call — which costs a second lookup and, worse, lets the act of logging
        trigger auth's own side effects.
        """
        if user_id is not None and new_scope is None:
            # Without a scope the resolver reads a dict nothing ever wrote to,
            # so every line would quietly lack `user_id`.
            raise ValueError("user_id requires new_scope; pass both or neither")
        super().__init__(**kwargs)
        self.structured_logging = structured
        self._user_id = user_id or (lambda: None)
        self._new_scope = new_scope or (lambda: None)

    async def on_message(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        # Fresh scope per call, so one request can never read another's identity.
        self._new_scope()
        watchdog = asyncio.ensure_future(self._note_if_still_running(context))
        try:
            return await super().on_message(context, call_next)
        finally:
            watchdog.cancel()

    async def _note_if_still_running(self, context: MiddlewareContext[Any]) -> None:
        """The only line a hung call ever produces.

        Dropping the `*_start` half buys one line per call, but a call that
        never returns never reaches its completion line either — so without
        this it is invisible: no target, no user, no sign it began.
        """
        await asyncio.sleep(SLOW_CALL_SECONDS)
        message: dict[str, str | int | float] = {
            "event": "request_in_flight",
            "method": context.method or "unknown",
            "source": context.source,
            "elapsed_ms": round(SLOW_CALL_SECONDS * 1000, 2),
        }
        self._log_message(self._annotate(message, context), logging.WARNING)

    def _log_message(
        self, message: dict[str, str | int | float], log_level: int | None = None
    ) -> None:
        # Drop the `*_start` half: one line per call, not two.
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
        # The class, never the message: `tool_errors` keeps domain ValueError
        # text intact and service validation echoes user input back.
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
        user_id = self._user_id()
        if user_id is not None:
            message["user_id"] = user_id
        return message
