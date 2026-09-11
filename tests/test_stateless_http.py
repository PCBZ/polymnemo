"""The MCP HTTP transport must be STATELESS, so any replica can serve any
request.

Azure Container Apps / GCP Cloud Run run several replicas behind a round-robin
ingress with no session affinity. A *stateful* Streamable-HTTP session is held
in one replica's memory, so a follow-up request that lands on a different
replica can't find it. With min_replicas=0/1 this never surfaces (only one
replica), but it breaks mid-conversation once the service scales out.

We reproduce that exactly: two independent ASGI app instances stand in for two
replicas (each has its own in-memory session store), and a request is routed
cross-replica.

- stateful  -> replica B never saw the session -> rejected  (the pre-fix bug)
- stateless -> any replica serves the request  -> 200        (the fix)

The stateful case failing here is also what proves the two-replica simulation is
real (the two apps genuinely have separate session stores).
"""

from __future__ import annotations

import contextlib

import httpx
import pytest
from asgi_lifespan import LifespanManager

from polymnemo.config import settings
from polymnemo.server import mcp

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
# `ping` is the one tool that needs no auth (it never resolves current_user), so
# this exercises the transport session in isolation from the auth layer.
_PING = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "ping", "arguments": {}},
}


@contextlib.asynccontextmanager
async def _replica(stateless: bool):
    """One 'replica' = an independent ASGI app instance with its own session store."""
    app = mcp.http_app(stateless_http=stateless)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://replica"
        ) as client:
            yield client


@pytest.mark.parametrize("stateless", [False, True])
async def test_request_survives_cross_replica_routing(stateless: bool) -> None:
    async with (
        _replica(stateless) as replica_a,
        _replica(stateless) as replica_b,
    ):
        # initialize on replica A — a stateful server creates the session here.
        init = await replica_a.post(settings.mcp_path, json=_INIT, headers=_HEADERS)
        assert init.status_code == 200
        session_id = init.headers.get("mcp-session-id")

        # a follow-up request routed to replica B (the round-robin case).
        headers = dict(_HEADERS)
        if session_id:
            headers["mcp-session-id"] = session_id
        resp = await replica_b.post(settings.mcp_path, json=_PING, headers=headers)

        if stateless:
            # any replica can serve any request -> the fix works.
            assert resp.status_code == 200, resp.text
            assert "polymnemo" in resp.text
        else:
            # replica B never saw the session -> rejected (the pre-fix failure,
            # and proof the two replicas have independent session stores).
            assert resp.status_code in (400, 404), resp.text
            assert "session" in resp.text.lower()
