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

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from . import app
from .auth import AuthError
from .ratelimit import RateLimitError


def current_user() -> str:
    """Resolve the caller's ``user_id`` from the request's bearer key.

    Raises a ToolError (surfaced to the model) if authentication fails.
    """
    # get_http_headers() strips `authorization` by default; opt it back in.
    headers = get_http_headers(include={"authorization"})
    try:
        return app.ctx.auth.authenticate(headers)
    except AuthError as exc:
        raise ToolError(f"Authentication failed: {exc}") from exc


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
