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
import time
from collections.abc import Callable
from typing import Any

from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext

logger = logging.getLogger("polymnemo")

CALL_LOGGER = "polymnemo.calls"

# A 401 is raised before any middleware, so this logger is the only record of
# one. Auth modules reach it via `getLogger(__name__)`, inheriting this level.
AUTH_LOGGER = "polymnemo.auth"

# A call that never returns emits no completion line, so it needs its own.
SLOW_CALL_SECONDS = 10.0

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(*, structured: bool, level: str) -> None:
    """Install the root handler. Called from the entry point, never on import."""
    resolved = getattr(logging, level.upper(), logging.INFO)
    # `getattr` finds any attribute, not just levels: BASIC_FORMAT is a str.
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        # In json mode the record IS the object, so nothing may precede it.
        format="%(message)s" if structured else TEXT_FORMAT,
        # Stricter of the two: raising `level` quietens libraries too.
        level=max(logging.INFO, resolved),
        # Without this the format is ignored: root already has a handler.
        # Note it closes every existing one — attach an SDK's handler after
        # this runs, or to a named logger, or it goes dark silently.
        force=True,
    )
    logging.getLogger("polymnemo").setLevel(resolved)
    # Its own level: upstream splits ERROR/INFO, so WARNING would drop the
    # successes and every error-rate query would read 100%.
    logging.getLogger(CALL_LOGGER).setLevel(logging.INFO)
    # Never above WARNING, or LOG_LEVEL=ERROR silences every 401.
    logging.getLogger(AUTH_LOGGER).setLevel(min(resolved, logging.WARNING))


def _target(context: MiddlewareContext[Any]) -> str | None:
    """The tool's name, or the resource's URI. Upstream only logs ``method``,
    which is always ``tools/call`` and so answers nothing per-tool."""
    message = getattr(context, "message", None)
    # `is not None`: an empty name is an anomaly to report, not to drop.
    name = getattr(message, "name", None)  # tools/call, prompts/get
    if name is not None:
        return str(name)
    uri = getattr(message, "uri", None)  # resources/read
    if uri is not None:
        return str(uri)
    return None


class CallLogMiddleware(StructuredLoggingMiddleware):
    """One line per completed call, carrying ``user_id`` and no message text.
    A call still running after ``SLOW_CALL_SECONDS`` adds one more.

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
        if (user_id is None) != (new_scope is None):
            # Either alone yields lines with no `user_id`, silently.
            raise ValueError("pass both user_id and new_scope, or neither")
        super().__init__(**kwargs)
        self.structured_logging = structured
        self._user_id = user_id or (lambda: None)
        self._new_scope = new_scope or (lambda: None)

    async def on_message(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        # Fresh scope per call, so one request can never read another's identity.
        self._new_scope()
        started = time.perf_counter()
        watchdog = asyncio.create_task(self._note_if_still_running(context, started))
        try:
            return await super().on_message(context, call_next)
        finally:
            watchdog.cancel()

    async def _note_if_still_running(
        self, context: MiddlewareContext[Any], started: float
    ) -> None:
        """The only line a hung call ever produces.

        Dropping the `*_start` half buys one line per call, but a call that
        never returns never reaches its completion line either — so without
        this it is invisible: no target, no user, no sign it began.

        A call that crosses the threshold and *then* finishes logs twice, on
        purpose: one line saying it was still running, one saying how it ended.
        Suppressing either would lose a fact worth having.
        """
        await asyncio.sleep(SLOW_CALL_SECONDS)
        message: dict[str, str | int | float] = {
            "event": "request_in_flight",
            "method": context.method or "unknown",
            "source": context.source,
            # Measured: a loaded loop wakes late, and a constant here would
            # only ever repeat its own assumption.
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
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
        # The class, never the message: it can carry caller data.
        message["error"] = type(error).__name__
        return self._annotate(message, context)

    def _annotate(
        self,
        message: dict[str, str | int | float],
        context: MiddlewareContext[Any],
    ) -> dict[str, str | int | float]:
        # Defensive: `source` is a plain dataclass field, so its Literal type
        # is not enforced and a None would emit as null. `method` has the same
        # guard upstream.
        if message.get("source") is None:
            message["source"] = "unknown"
        target = _target(context)
        if target is not None:
            message["target"] = target
        user_id = self._user_id()
        if user_id is not None:
            message["user_id"] = user_id
        return message
