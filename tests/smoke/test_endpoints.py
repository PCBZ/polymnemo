"""Every route the deployment exposes answers the way it is supposed to (#129).

The deploy job calls a rollout good as soon as the app returns *any* HTTP
status, which only proves the container started and pulled an image. Two builds
have passed that bar while broken:

- #123 — `required_scopes` was enforced after `verify_token`, so every bearer
  key got 401 in production. Green deploy, 214 green unit tests, dead service.
- #128 — the token pages 404 unless OAuth is configured, and Terraform never
  injected `POLYMNEMO_LOG_FORMAT`, so the feature shipped inert.

Both live in the blind spot in-process tests cannot reach: configuration. So
this asserts each route's contract against a real deployment.

Read-only by design — nothing here writes a memory or mints a credential. It is
still pointed only at the TEST deployment: it authenticates and reads real rows,
and aiming that at production would mean keeping a key that opens production
memories in CI for the sake of a check.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

TIMEOUT = httpx.Timeout(30.0, connect=60.0)  # the app scales to zero: cold start

# A freshly applied revision is not serving yet — `terraform apply` returns when
# Azure accepts the revision spec, not when the container is up — and the image
# bakes in an embedding model, so a cold start is not quick. Paid once per
# session, and only actually spent when something is wrong. Overridable for the
# same reason the log suite's is: a deploy check can afford minutes of patience
# pointed at a URL that is wrong, and a developer cannot.
READY_TIMEOUT_SECONDS = int(os.environ.get("POLYMNEMO_SMOKE_READY_TIMEOUT", "300"))
READY_POLL_SECONDS = 5

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.fixture(scope="session")
def client(base_url: str):
    # Redirects are the contract here, so don't follow them.
    with httpx.Client(base_url=base_url, timeout=TIMEOUT, follow_redirects=False) as c:
        _wait_until_serving(c, base_url)
        yield c


def _wait_until_serving(client: httpx.Client, base_url: str) -> None:
    """Block until the deployment answers at all, so the assertions below are
    measuring its behaviour rather than its startup.

    Any HTTP status counts — the root is a 404 and /mcp a 405, and neither is
    what this is asking. It only wants to know that something is listening and
    speaking HTTP; what it *says* is every other test in this file. A 5xx does
    not count: that is the ingress with no healthy backend behind it, which is
    exactly the green-apply-dead-container case worth waiting through.
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    reason = "no response"
    while True:
        try:
            response = client.get("/")
            if response.status_code < 500:
                return
            reason = f"HTTP {response.status_code}"
        except httpx.RequestError as exc:
            reason = type(exc).__name__
        if time.monotonic() > deadline:
            break
        time.sleep(READY_POLL_SECONDS)
    pytest.fail(
        f"{base_url} never served a response within {READY_TIMEOUT_SECONDS}s "
        f"(last: {reason}) — the apply was green, so suspect the image: it is "
        "pulled from a PUBLIC GHCR package with no credentials."
    )


def _mcp(client, body, key: str | None = None):
    headers = dict(MCP_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return client.post("/mcp", headers=headers, json=body)


class TestMcpAuth:
    def test_an_unauthenticated_call_is_refused(self, client):
        assert _mcp(client, TOOLS_LIST).status_code == 401

    def test_an_unknown_bearer_is_refused(self, client):
        assert _mcp(client, TOOLS_LIST, "definitely-not-a-key").status_code == 401

    def test_a_valid_bearer_is_accepted(self, client, bearer_key):
        """#123: every bearer key 401'd in production while every test passed."""
        r = _mcp(client, TOOLS_LIST, bearer_key)
        assert r.status_code == 200, r.text[:300]

    def test_the_401_points_at_the_discovery_document(self, client):
        """How a client with no credential learns where to authenticate."""
        r = _mcp(client, TOOLS_LIST)
        challenge = r.headers.get("www-authenticate", "")
        assert "resource_metadata=" in challenge, challenge


class TestToolSurface:
    def test_the_expected_tools_are_exposed(self, client, bearer_key):
        names = _tool_names(_mcp(client, TOOLS_LIST, bearer_key).text)
        assert {"ping", "remember", "recall", "forget"} <= names, sorted(names)

    def test_no_token_tool_is_reachable(self, client, bearer_key):
        """Tokens are browser-only by design: a secret must never be reachable
        through a tool result."""
        names = _tool_names(_mcp(client, TOOLS_LIST, bearer_key).text)
        assert not {"create_token", "list_tokens", "revoke_token"} & names


class TestAnAuthenticatedToolCall:
    """`tools/list` only proves the tools are advertised. This invokes one, so
    the auth -> rate limit -> service -> store path is exercised on the real
    deployment — and it is what puts a `user_id` on a call-log line for the log
    job to find.

    `list_memories` because it is read-only, authenticates through
    `rate_limited`, and needs no embedding: a page of rows out of Postgres.
    """

    def test_it_succeeds_and_returns_a_page(self, client, bearer_key):
        r = _mcp(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_memories", "arguments": {"limit": 1}},
            },
            bearer_key,
        )
        assert r.status_code == 200, r.text[:300]
        result = _result(r.text)
        # Deliberately not echoing the payload: this points at production and
        # Actions logs on a public repo are public. Nothing is lost — a failed
        # call writes its error and cause class to the call log, which the log
        # job queries next.
        assert not result.get("isError"), "list_memories returned a tool error"


class TestTokenPages:
    def test_an_unauthenticated_visit_redirects_to_login(self, client):
        r = client.get("/tokens")
        assert r.status_code == 302
        assert r.headers["location"].endswith("/tokens/login")

    def test_login_hands_off_to_github_with_our_own_callback(self, client, base_url):
        """A 404 here means OAuth is unconfigured on this deployment, which is
        how the token pages silently disappear."""
        r = client.get("/tokens/login")
        assert r.status_code == 302, f"OAuth not configured? {r.status_code}"
        target = urlparse(r.headers["location"])
        assert target.netloc == "github.com"
        redirect = parse_qs(target.query).get("redirect_uri", [""])[0]
        assert redirect == f"{base_url}/tokens/callback", redirect

    def test_a_forged_state_is_refused(self, client):
        """Without this an attacker completes the flow with their own code and
        logs the victim into the attacker's account."""
        r = client.get("/tokens/callback", params={"code": "x", "state": "forged"})
        assert r.status_code == 400

    @pytest.mark.parametrize("path", ["/tokens/create", "/tokens/revoke"])
    def test_a_post_without_csrf_is_refused(self, client, path):
        assert client.post(path, data={"label": "smoke"}).status_code == 400

    def test_package_data_shipped_in_the_image(self, client):
        """Not a CSS test. This is the only unauthenticated route that reads a
        non-Python file out of the installed package — `templates/tokens.html`
        renders only behind a session cookie, which this suite cannot obtain.
        If a packaging change stops shipping `templates/`, every other symptom
        is behind a login."""
        r = client.get("/tokens/style.css")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/css")
        assert r.text.strip(), "stylesheet served empty"


class TestOAuthDiscovery:
    """Every URL in these documents is derived from the configured origin. Get
    it wrong and bearer keys keep working, /mcp keeps answering, the deploy
    stays green, and only OAuth clients break."""

    def test_authorization_server_metadata_points_at_this_host(self, client, base_url):
        r = client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        meta = r.json()
        for key in ("issuer", "authorization_endpoint", "token_endpoint"):
            assert meta[key].startswith(base_url), f"{key} -> {meta[key]}"

    def test_protected_resource_metadata_points_at_this_host(self, client, base_url):
        r = client.get("/.well-known/oauth-protected-resource/mcp")
        assert r.status_code == 200
        meta = r.json()
        assert meta["resource"] == f"{base_url}/mcp"
        assert any(s.startswith(base_url) for s in meta["authorization_servers"])

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/authorize"),
            ("POST", "/token"),
            ("POST", "/register"),
            ("GET", "/auth/callback"),
            ("GET", "/consent"),
        ],
    )
    def test_the_oauth_routes_are_mounted(self, client, method, path):
        """Only that they exist. A 404 means the provider did not mount, which
        is how a deployment loses the whole MCP OAuth flow while /mcp still
        answers bearer keys."""
        assert client.request(method, path).status_code != 404


class TestNothingReturnsServerError:
    @pytest.mark.parametrize(
        "path",
        [
            "/tokens",
            "/tokens/login",
            "/tokens/style.css",
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource/mcp",
        ],
    )
    def test_no_5xx(self, client, path):
        r = client.get(path)
        assert r.status_code < 500, f"{path} -> {r.status_code}: {r.text[:200]}"


def _frames(body: str) -> Iterator[dict]:
    """JSON objects out of a response body, plain or SSE-framed.

    One place to fix when the framing changes, instead of two scanners that
    have to agree.
    """
    for line in body.splitlines():
        line = line.removeprefix("data:").strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _result(body: str) -> dict:
    """The `result` object out of a JSON-RPC reply."""
    for payload in _frames(body):
        if "result" in payload:
            return payload["result"]
        _raise_if_error(payload)
    raise AssertionError(f"no JSON-RPC result in response: {body[:300]}")


def _tool_names(body: str) -> set[str]:
    """Tool names out of a tools/list reply."""
    for payload in _frames(body):
        tools = payload.get("result", {}).get("tools")
        if tools is not None:
            return {t["name"] for t in tools}
        _raise_if_error(payload)
    raise AssertionError(f"no tools/list result in response: {body[:300]}")


def _raise_if_error(payload: dict) -> None:
    """Surface a JSON-RPC error instead of letting the scan fall through.

    Without this, "every bearer key is refused" — the exact bug this suite
    exists to catch — surfaces as a confusing "no result in response" parser
    failure with the actual error object nowhere in the output.
    """
    if "error" in payload:
        raise AssertionError(f"JSON-RPC error: {payload['error']}")
