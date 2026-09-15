"""Token pages (#125) — the security properties, not the markup.

What's worth testing here is what an attacker would try: forging a session
cookie, replaying an expired one, posting a form from another site, or
completing the OAuth callback with their own code to log a victim into the
attacker's account.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

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


class _StoreWithOneToken:
    """Only `list_for_user` is used by the page renderer."""

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        now = datetime(2026, 9, 14, tzinfo=UTC)
        return [
            ApiToken(
                id="a1",
                user_id=user_id,
                label="ci-runner",
                created_at=now,
                expires_at=None,
            )
        ]


class TestPages:
    def test_reveal_block_is_hidden_when_there_is_no_new_token(self):
        """The reveal block is always in the markup and hidden by attribute, so
        the `hidden` must actually be there on an ordinary page load."""
        # The exact attribute, not just the word "hidden": the CSRF field is an
        # `<input type="hidden">`, so a loose match passes even when the reveal
        # block is wide open.
        plain = web._tokens_page(None, "github:1", "csrf", "https://e.test")
        assert '<div class="card" hidden>' in plain.body.decode()
        fresh = web._tokens_page(
            None, "github:1", "csrf", "https://e.test", fresh="pmn_x"
        )
        assert '<div class="card" hidden>' not in fresh.body.decode()

    def test_empty_state_shows_only_when_there_are_no_tokens(self):
        """Same attribute trick as the reveal block: the "no tokens" row is
        always in the table and hidden once there is a real row."""
        empty = web._tokens_page(None, "github:1", "csrf", "https://e.test")
        assert '<tr><td colspan="4" class="meta">No tokens yet.' in empty.body.decode()
        full = web._tokens_page(
            _StoreWithOneToken(), "github:1", "csrf", "https://e.test"
        ).body.decode()
        assert "<tr hidden>" in full
        assert "<td>ci-runner</td>" in full

    def test_user_id_is_escaped(self):
        """A GitHub login can't contain markup today, but the page must not
        depend on that."""
        page = web._tokens_page(
            None, "github:<script>x</script>", "csrf", "https://e.test"
        )
        body = page.body.decode()
        assert "<script>x</script>" not in body
        assert "&lt;script&gt;" in body

    def test_new_token_is_shown_with_a_warning(self):
        body = web._tokens_page(
            None, "github:1", "csrf", "https://e.test", fresh="pmn_secret"
        ).body.decode()
        assert "pmn_secret" in body
        # Normalised: the warning wraps in the template, and a test shouldn't
        # break when someone reflows the HTML.
        assert "cannot be shown again" in " ".join(body.split())
