"""Tool plumbing — the wrappers between MCP transport and the service.

Three cross-cutting concerns, kept out of ``server`` so the tool definitions read
cleanly:

- ``current_user`` — per-user auth (resolve the bearer key to a ``user_id``).
- ``rate_limited`` — the GLOBAL rate-limit gate (a decorator; not per-user).
- ``tool_errors`` — map domain ``ValueError``s to actionable ``ToolError``s.

They read the running context from ``app`` (not ``server``) to avoid a cycle.
"""

from __future__ import annotations

import functools
from contextvars import ContextVar

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from . import app
from .auth import AuthError
from .ratelimit import RateLimitError

# Per-request scratch space. A ContextVar holding a *mutable* dict, not a bare
# value: each task gets its own copy of the context, so concurrent requests
# can't see each other's, and mutating the dict (rather than rebinding the var)
# is visible to the caller even when a sync tool runs in a worker thread.
_REQUEST: ContextVar[dict[str, str] | None] = ContextVar("request_scope", default=None)


def new_request_scope() -> None:
    """Start a request's scope. Called once per call, before the tool runs."""
    _REQUEST.set({})


def _scope() -> dict[str, str]:
    """This request's scope, creating one if the caller never opened it.

    ``_REQUEST.get({})`` would hand back a throwaway dict, so writing to it is a
    no-op and the identity vanishes with no error — which is what happens to any
    path that reaches ``current_user`` without the middleware, such as a test or
    a background task. Binding it here makes the write land instead. The binding
    is task-local, so this cannot leak one request's identity into another.
    """
    scope = _REQUEST.get(None)
    if scope is None:
        scope = {}
        _REQUEST.set(scope)
    return scope


def current_user_id() -> str | None:
    """The ``user_id`` this request authenticated as, or None if it never did.

    Read-only: it reports what ``current_user`` resolved rather than resolving
    again, so a caller (the call log) can name the identity without re-running
    authentication or being able to trigger its side effects.
    """
    scope = _REQUEST.get(None)
    return scope.get("user_id") if scope else None


def current_user() -> str:
    """Resolve the caller's ``user_id`` from the request's bearer key.

    Raises a ToolError (surfaced to the model) if authentication fails.
    """
    # get_http_headers() strips `authorization` by default; opt it back in.
    headers = get_http_headers(include={"authorization"})
    try:
        user_id = app.ctx.auth.authenticate(headers)
    except AuthError as exc:
        raise ToolError(f"Authentication failed: {exc}") from exc
    _scope()["user_id"] = user_id
    return user_id


def rate_limited(cost: int = 1):
    """Authenticate the caller, then charge the GLOBAL rate-limit bucket ``cost``
    tokens before the tool runs.

    Auth runs **first**, by design: the bucket is server-wide, so charging it
    before rejecting anonymous callers would let junk traffic drain the shared
    budget and lock out real users — and requests rejected at auth do no
    embedding, so they shouldn't spend the budget either. The limit itself is
    global, **not** per-user. Embed-heavy tools pass a higher ``cost``; over the
    limit surfaces as a ``ToolError``.
    """

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            current_user()  # authenticate first: reject anon before charging
            if app.ctx.rate_limiter is not None:
                try:
                    app.ctx.rate_limiter.check(cost)
                except RateLimitError as exc:
                    raise ToolError(str(exc)) from exc
            return fn(*args, **kwargs)

        return wrapper

    return decorate


def tool_errors(fn):
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
