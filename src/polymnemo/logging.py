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
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext

logger = logging.getLogger("polymnemo")

CALL_LOGGER = "polymnemo.calls"

# A 401 is raised before any middleware, so this logger is the only record of
# one. Auth modules reach it via `getLogger(__name__)`, inheriting this level.
AUTH_LOGGER = "polymnemo.auth"

# Credential lifecycle. Like the auth log, it answers a question that cannot be
# reconstructed later, so `log_level` must not be able to raise it out of view.
AUDIT_LOGGER = "polymnemo.audit"

# A call that never returns emits no completion line, so it needs its own.
SLOW_CALL_SECONDS = 10.0

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Shared with the tests, so rewording it stays a one-line change.
SCOPE_PAIR_ERROR = "pass both user_id and new_scope, or neither"


class JsonFormatter(logging.Formatter):
    """One JSON object per record, for every logger — not just the call log.

    Emitting `%(message)s` alone was cheaper but lost the level, timestamp and
    logger name from every prose line, so a 401 burst, a rate-limit hit and a
    leaked blob were indistinguishable by severity in the very mode they were
    written for. It also let a newline inside a logged value forge a second
    line; `json.dumps` escapes it.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
        }
        # The call log hands over its fields; everything else is a sentence.
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        else:
            payload["message"] = record.getMessage()
        if record.exc_info:
            payload["exc_type"] = (
                record.exc_info[0].__name__ if record.exc_info[0] else None
            )
        return json.dumps(payload, default=str)


def _install_levels(resolved: int) -> None:
    """Which streams `log_level` may silence, and which it may not.

    A table rather than a run of setLevel statements: the difference between
    "pinned", "capped" and "follows the setting" lived only in comments, and
    every new stream that must survive LOG_LEVEL=ERROR added another line.
    """
    policy: dict[str, int] = {
        # Access log: always on, because upstream splits ERROR/INFO and losing
        # the successes makes every error-rate query read 100%.
        CALL_LOGGER: logging.INFO,
        # A 401 is the only record of a credential-stuffing run.
        AUTH_LOGGER: min(resolved, logging.WARNING),
        # Who minted or revoked a credential, and when.
        AUDIT_LOGGER: min(resolved, logging.INFO),
        # Our own warnings are actionable; INFO/DEBUG chatter follows `level`.
        "polymnemo": min(resolved, logging.WARNING),
    }
    for name, value in policy.items():
        logging.getLogger(name).setLevel(value)


def configure_logging(*, structured: bool, level: str) -> None:
    """Install the root handler. Called from the entry point, never on import."""
    resolved = getattr(logging, level.upper(), logging.INFO)
    # `getattr` finds any attribute, not just levels: BASIC_FORMAT is a str.
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        format=TEXT_FORMAT,
        # Capped at WARNING: raising `level` quietens libraries, but never past
        # their warnings — SQLAlchemy pool exhaustion is exactly what you want
        # to still see on a replica someone set to ERROR.
        level=min(max(logging.INFO, resolved), logging.WARNING),
        # Without this the format is ignored: root already has a handler.
        # Note it closes every existing one — attach an SDK's handler after
        # this runs, or to a named logger, or it goes dark silently.
        force=True,
    )
    if structured:
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter())
    _install_levels(resolved)


def _target(context: MiddlewareContext[Any]) -> str | None:
    """The tool's name, or the resource's URI. Upstream only logs ``method``,
    which is always ``tools/call`` and so answers nothing per-tool."""
    message = getattr(context, "message", None)
    # A Mapping, not a model, on the root dispatch: FastMCP hands `on_message`
    # the raw params for anything the interior never dispatched (a malformed
    # or unroutable tools/call), and getattr misses `name` sitting in the dict.
    if isinstance(message, Mapping):
        for key in ("name", "uri"):
            value = message.get(key)
            if value is not None:
                return str(value)
        return None
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
            raise ValueError(SCOPE_PAIR_ERROR)
        super().__init__(**kwargs)
        self.structured_logging = structured
        # `is None`, matching the guard above: `or` would swap out a callable
        # that is merely falsy, producing the silent no-user_id case the guard
        # exists to reject.
        self._user_id = (lambda: None) if user_id is None else user_id
        self._new_scope = (lambda: None) if new_scope is None else new_scope

    async def on_message(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        # Fresh scope per call, so one request can never read another's identity.
        self._new_scope()
        started = time.perf_counter()
        watchdog = asyncio.create_task(self._note_if_still_running(context, started))
        try:
            return await super().on_message(context, call_next)
        except BaseException as exc:
            # CancelledError is a BaseException, so upstream's `except
            # Exception` never sees it: a client disconnect or a shutdown left
            # the call with no completion line and no in-flight line either —
            # completely invisible, which is the blind spot the watchdog exists
            # to close. Only cancellation reaches here; Exception is already
            # logged and re-raised upstream.
            if isinstance(exc, asyncio.CancelledError):
                self._log_message(
                    self._annotate(
                        {
                            "event": f"{context.type}_cancelled",
                            "method": context.method or "unknown",
                            "source": context.source,
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        },
                        context,
                    ),
                    logging.WARNING,
                )
            raise
        finally:
            # cancel() without awaiting: the task is reaped on the next tick,
            # and awaiting it here measured 13.5 -> 47.9 µs per call.
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
        if self.structured_logging:
            # Hand the fields over rather than pre-serialising, so JsonFormatter
            # can put `ts`/`level`/`logger` alongside them instead of nesting a
            # JSON string inside a JSON string.
            self.logger.log(
                log_level or self.log_level,
                str(message.get("event", "")),
                extra={"fields": message},
            )
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
        # The class, never the message: it can carry caller data. The cause
        # too, because `tool_errors`, `rate_limited` and `current_user` all
        # normalise to ToolError — without it every in-tool failure reads the
        # same and an error-rate spike can't be diagnosed.
        message["error"] = type(error).__name__
        cause = error.__cause__
        if cause is not None:
            message["cause"] = type(cause).__name__
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
        try:
            user_id = self._user_id()
        except Exception:
            # An injected resolver that raises would otherwise be caught by
            # upstream's `except Exception`, called a second time from the
            # error path, and escape — turning a successful call into a
            # failure. Logging must not break the thing it logs.
            user_id = None
        if user_id is not None:
            message["user_id"] = user_id
        return message
