from dataclasses import replace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from polymnemo.ratelimit import GlobalRateLimiter, RateLimitError


def test_allows_up_to_limit_then_denies():
    rl = GlobalRateLimiter(per_min=3)
    rl.check()
    rl.check()
    rl.check()  # 3 within the window
    with pytest.raises(RateLimitError):
        rl.check()  # 4th over the limit


def test_cost_weighting():
    rl = GlobalRateLimiter(per_min=3)
    rl.check(cost=2)  # uses 2 of 3
    with pytest.raises(RateLimitError):
        rl.check(cost=2)  # 2 + 2 > 3


def test_context_enabled_flag(monkeypatch):
    from polymnemo import context
    from polymnemo.config import settings

    monkeypatch.setattr(settings, "ratelimit_enabled", False)
    assert context._build_rate_limiter() is None  # disabled -> no limiter

    monkeypatch.setattr(settings, "ratelimit_enabled", True)
    assert isinstance(context._build_rate_limiter(), GlobalRateLimiter)


async def test_tool_over_limit_returns_toolerror(monkeypatch):
    # Swap the running ctx's limiter (read by @rate_limited) for a tiny bucket;
    # remember costs 2, so one succeeds and the next is denied.
    from polymnemo import app, server

    limiter = GlobalRateLimiter(per_min=2)
    monkeypatch.setattr(app, "ctx", replace(app.ctx, rate_limiter=limiter))
    app.ctx.store._rows.clear()
    try:
        async with Client(server.mcp) as client:
            await client.call_tool("remember", {"content": "one"})  # cost 2 -> full
            with pytest.raises(ToolError) as exc:
                await client.call_tool("remember", {"content": "two"})
            assert "rate limit" in str(exc.value).lower()
    finally:
        app.ctx.store._rows.clear()
