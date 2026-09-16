"""Token pages (#125) — the security properties, not the markup.

What's worth testing here is what an attacker would try: forging a session
cookie, replaying an expired one, posting a form from another site, or
completing the OAuth callback with their own code to log a victim into the
attacker's account.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import pytest

from polymnemo import web
from polymnemo.auth.tokens import ApiToken


@pytest.fixture(autouse=True)
def _oauth_configured(monkeypatch):
    """The cookie signing key derives from the OAuth secret, so it has to exist."""
    monkeypatch.setattr(web.settings, "oauth_client_secret", "test-secret")


class _FakeRequest:
    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


class TestSessionCookie:
    def test_round_trip(self):
        cookie = web._new_session("github:123")
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: cookie})) == (
            "github:123"
        )

    def test_tampered_payload_is_rejected(self):
        """Swapping the user id must invalidate the signature — otherwise anyone
        could sign in as anyone by editing a cookie."""
        cookie = web._new_session("github:123")
        payload, _, mac = cookie.rpartition(".")
        forged = payload.replace("github:123", "github:999") + "." + mac
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: forged})) is None

    def test_unsigned_cookie_is_rejected(self):
        raw = json.dumps({"sub": "github:999", "exp": time.time() + 999})
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: raw})) is None

    def test_expired_session_is_rejected(self):
        """Expiry lives inside the signed payload, so it can't be extended by
        changing the browser's clock or the cookie's Max-Age."""
        expired = web._sign(
            json.dumps({"sub": "github:123", "exp": int(time.time()) - 1})
        )
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: expired})) is None

    def test_signature_from_a_different_secret_is_rejected(self, monkeypatch):
        cookie = web._new_session("github:123")
        monkeypatch.setattr(web.settings, "oauth_client_secret", "rotated-secret")
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: cookie})) is None

    def test_no_cookie_is_anonymous(self):
        assert web._session_user(_FakeRequest({})) is None


class TestCsrf:
    def test_matching_token_passes(self):
        cookie = web._new_session("github:123")
        request = _FakeRequest({web.SESSION_COOKIE: cookie})
        csrf = web._session_csrf(request)
        assert web._csrf_ok(request, {"csrf": csrf})

    def test_missing_token_is_rejected(self):
        cookie = web._new_session("github:123")
        request = _FakeRequest({web.SESSION_COOKIE: cookie})
        assert not web._csrf_ok(request, {})

    def test_token_from_another_session_is_rejected(self):
        """A CSRF value lifted from one user's page must not work against
        another's session."""
        other = _FakeRequest({web.SESSION_COOKIE: web._new_session("github:999")})
        mine = _FakeRequest({web.SESSION_COOKIE: web._new_session("github:123")})
        assert not web._csrf_ok(mine, {"csrf": web._session_csrf(other)})

    def test_anonymous_request_is_rejected(self):
        assert not web._csrf_ok(_FakeRequest({}), {"csrf": "anything"})


def _one_token() -> list[ApiToken]:
    return [
        ApiToken(
            id="a1",
            user_id="github:1",
            label="ci-runner",
            created_at=datetime(2026, 9, 14, tzinfo=UTC),
            expires_at=None,
        )
    ]


class _RouteRecorder:
    """Stands in for the FastMCP server: records what `register` mounts, and
    keeps the handlers so a route can be driven directly."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.handlers: dict[str, object] = {}

    def custom_route(self, path: str, methods: list[str]):
        self.paths.append(path)

        def keep(fn):
            self.handlers[path] = fn
            return fn

        return keep


class TestPages:
    def test_reveal_block_is_hidden_when_there_is_no_new_token(self):
        """The reveal block is always in the markup and hidden by attribute, so
        the `hidden` must actually be there on an ordinary page load."""
        # The exact attribute, not just the word "hidden": the CSRF field is an
        # `<input type="hidden">`, so a loose match passes even when the reveal
        # block is wide open.
        plain = web._tokens_page([], "github:1", "csrf", "https://e.test")
        assert '<div class="card" hidden>' in plain.body.decode()
        fresh = web._tokens_page(
            [], "github:1", "csrf", "https://e.test", fresh="pmn_x"
        )
        assert '<div class="card" hidden>' not in fresh.body.decode()

    def test_empty_state_shows_only_when_there_are_no_tokens(self):
        """Same attribute trick as the reveal block: the "no tokens" row is
        always in the table and hidden once there is a real row."""
        empty = web._tokens_page([], "github:1", "csrf", "https://e.test")
        assert '<tr><td colspan="4" class="meta">No tokens yet.' in empty.body.decode()
        full = web._tokens_page(
            _one_token(), "github:1", "csrf", "https://e.test"
        ).body.decode()
        assert "<tr hidden>" in full
        assert "<td>ci-runner</td>" in full

    def test_user_id_is_escaped(self):
        """A GitHub login can't contain markup today, but the page must not
        depend on that."""
        page = web._tokens_page(
            [], "github:<script>x</script>", "csrf", "https://e.test"
        )
        body = page.body.decode()
        assert "<script>x</script>" not in body
        assert "&lt;script&gt;" in body

    def test_new_token_is_shown_with_a_warning(self):
        body = web._tokens_page(
            [], "github:1", "csrf", "https://e.test", fresh="pmn_secret"
        ).body.decode()
        assert "pmn_secret" in body
        # Normalised: the warning wraps in the template, and a test shouldn't
        # break when someone reflows the HTML.
        assert "cannot be shown again" in " ".join(body.split())


class TestOAuthUnconfigured:
    """Without OAuth the pages must not exist: the signing key would derive from
    an empty secret, so anyone could forge a session and POST /tokens/create."""

    def test_secret_refuses_to_derive_from_an_empty_client_secret(self, monkeypatch):
        monkeypatch.setattr(web.settings, "oauth_client_secret", "")
        with pytest.raises(RuntimeError, match="POLYMNEMO_OAUTH_CLIENT_SECRET"):
            web._secret()

    def test_no_routes_are_mounted(self, monkeypatch):
        monkeypatch.setattr(web.settings, "oauth_client_id", "")
        monkeypatch.setattr(web.settings, "oauth_client_secret", "")
        recorder = _RouteRecorder()
        web.register(recorder, None)
        assert recorder.paths == []

    def test_routes_are_mounted_once_oauth_is_configured(self, monkeypatch):
        monkeypatch.setattr(web.settings, "oauth_client_id", "id")
        monkeypatch.setattr(web.settings, "oauth_client_secret", "secret")
        monkeypatch.setattr(web.settings, "oauth_base_url", "https://e.test")
        recorder = _RouteRecorder()
        web.register(recorder, None)
        assert "/tokens" in recorder.paths
        assert "/tokens/create" in recorder.paths


class TestExpiryLabel:
    def test_expired_token_is_marked(self):
        past = datetime(2020, 1, 1, tzinfo=UTC)
        assert web._expiry_label(past) == "2020-01-01 (expired)"

    def test_live_token_is_not_marked(self):
        future = datetime.now(UTC) + timedelta(days=30)
        assert "(expired)" not in web._expiry_label(future)

    def test_no_expiry_reads_never(self):
        assert web._expiry_label(None) == "never"

    def test_naive_timestamp_does_not_raise(self):
        """Rows predating the tz-aware column come back naive; comparing them
        against an aware `now` would raise TypeError."""
        assert web._expiry_label(datetime(2020, 1, 1)) == "2020-01-01 (expired)"


class TestRevokeFeedback:
    """`revoke` returns False when no row matched — already gone, or not this
    user's. Redirecting anyway reports success for something that didn't
    happen."""

    class _PostRequest:
        def __init__(self, cookie: str, csrf: str, token_id: str) -> None:
            self.cookies = {web.SESSION_COOKIE: cookie}
            self.headers = {"host": "e.test"}
            self.url = type("U", (), {"scheme": "https"})()
            self._form = {"csrf": csrf, "id": token_id}

        async def form(self):
            return self._form

    class _Store:
        def __init__(self, result: bool) -> None:
            self.result = result

        def revoke(self, user_id: str, token_id: str) -> bool:
            return self.result

    def _handler(self, monkeypatch, store):
        monkeypatch.setattr(web.settings, "oauth_client_id", "id")
        monkeypatch.setattr(web.settings, "oauth_base_url", "https://e.test")
        recorder = _RouteRecorder()
        web.register(recorder, store)
        return recorder.handlers["/tokens/revoke"]

    def _request(self):
        cookie = web._new_session("github:1")
        csrf = web._session_csrf(_FakeRequest({web.SESSION_COOKIE: cookie}))
        return self._PostRequest(cookie, csrf or "", "a1")

    async def test_failed_revoke_is_reported(self, monkeypatch):
        handler = self._handler(monkeypatch, self._Store(False))
        response = await handler(self._request())
        assert response.status_code == 400
        assert b"already revoked" in response.body

    async def test_successful_revoke_redirects(self, monkeypatch):
        handler = self._handler(monkeypatch, self._Store(True))
        response = await handler(self._request())
        assert response.status_code == 302


class TestSignInFailureIsDiagnosable:
    """Drives `tokens_callback` with a client that fails, because asserting on
    web.py's source only proved the literal appears somewhere in the file —
    even in unreachable code — and the deleted alternative asserted nothing
    but that httpx renders its own constructor argument."""

    class _Request:
        def __init__(self, state: str, cookie: str) -> None:
            self.cookies = {web.STATE_COOKIE: cookie}
            self.headers = {"host": "e.test"}
            self.url = type("U", (), {"scheme": "https"})()
            self.query_params = {"code": "abc", "state": state}

    def _callback(self, monkeypatch):
        monkeypatch.setattr(web.settings, "oauth_client_id", "id")
        monkeypatch.setattr(web.settings, "oauth_base_url", "https://e.test")
        recorder = _RouteRecorder()
        web.register(recorder, None)
        return recorder.handlers["/tokens/callback"]

    def _request(self):
        state = "s3cr3t-state"
        return self._Request(state, web._sign(state))

    async def test_the_exception_message_reaches_the_log(self, caplog, monkeypatch):
        import httpx

        class _Failing:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                raise httpx.ConnectTimeout("timed out reaching api.github.com")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Failing())
        handler = self._callback(monkeypatch)
        with caplog.at_level(logging.WARNING):
            response = await handler(self._request())
        assert response.status_code == 400
        line = next(
            r.getMessage() for r in caplog.records if "sign-in failed" in r.getMessage()
        )
        # Both halves: the class alone can't tell a timeout from a 503.
        assert "ConnectTimeout" in line
        assert "api.github.com" in line

    async def test_the_oauth_code_never_reaches_the_log(self, caplog, monkeypatch):
        import httpx

        class _Failing:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                raise httpx.ReadTimeout("read timeout")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Failing())
        handler = self._callback(monkeypatch)
        with caplog.at_level(logging.DEBUG):
            await handler(self._request())
        assert "abc" not in " ".join(r.getMessage() for r in caplog.records)
