"""Multi-provider sign-in (#153) — identity separation and the flow's guards.

The decision this file protects: a GitHub login and a Google login are
DIFFERENT users. Someone may keep a personal and a work account, and a change
that quietly merged them would hand one account's memory to the other.
"""

from __future__ import annotations

import json
import time

import pytest

from polymnemo import web
from polymnemo.auth import providers


@pytest.fixture(autouse=True)
def _oauth_configured(monkeypatch):
    """The cookie signing key derives from the OAuth secret, so it has to exist."""
    monkeypatch.setattr(web.settings, "oauth_client_secret", "test-secret")
    monkeypatch.setattr(web.settings, "oauth_client_id", "gh-id")


@pytest.fixture
def _google(monkeypatch):
    monkeypatch.setattr(web.settings, "google_client_id", "goog-id")
    monkeypatch.setattr(web.settings, "google_client_secret", "goog-secret")


class TestIdentitiesStaySeparate:
    def test_the_same_subject_is_two_users(self):
        """The whole point of #153: identical account ids from two providers
        must not collapse onto one user_id."""
        assert providers.GITHUB.subject_prefix != providers.GOOGLE.subject_prefix
        github = f"{providers.GITHUB.subject_prefix}12345"
        google = f"{providers.GOOGLE.subject_prefix}12345"
        assert github != google

    def test_mcp_and_browser_agree_on_the_github_prefix(self):
        """A GitHub user reaching the server through MCP OAuth and through the
        token page must land on one user_id, not two."""
        from polymnemo.auth.oauth import GITHUB_SUBJECT_PREFIX

        assert GITHUB_SUBJECT_PREFIX == providers.GITHUB.subject_prefix

    def test_subject_comes_from_a_stable_id_never_an_email(self):
        """An email can be reassigned; the next holder would inherit memory."""
        assert providers.GOOGLE.subject_field == "sub"
        assert providers.GITHUB.subject_field == "id"


class TestOnlyConfiguredProvidersAreReachable:
    def test_unconfigured_provider_is_not_offered(self):
        assert [p.key for p in providers.enabled()] == ["github"]

    def test_unconfigured_provider_cannot_be_started_by_url(self):
        """Otherwise a crafted /tokens/login/google would begin a flow with an
        empty client_id against a provider the operator never enabled."""
        assert providers.get("google") is None

    def test_unknown_provider_is_rejected(self):
        assert providers.get("myspace") is None

    def test_both_are_offered_once_google_is_configured(self, _google):
        assert [p.key for p in providers.enabled()] == ["github", "google"]
        assert providers.get("google") is providers.GOOGLE


class TestStateCookieBindsTheProvider:
    def test_round_trip_carries_the_provider(self):
        signed = web._sign("google|abc123")
        key, _, state = (web._unsign(signed) or "").partition("|")
        assert (key, state) == ("google", "abc123")

    def test_swapping_the_provider_breaks_the_signature(self):
        """Else a code issued by one provider could be redeemed as another,
        letting an attacker land on a victim's user_id."""
        signed = web._sign("google|abc123")
        forged = signed.replace("google", "github", 1)
        assert web._unsign(forged) is None


class TestChooser:
    def test_lists_every_configured_provider(self, _google):
        html = _signin_html()
        assert "Continue with GitHub" in html
        assert "Continue with Google" in html

    def test_omits_the_unconfigured_one(self):
        html = _signin_html()
        assert "Continue with GitHub" in html
        assert "Google" not in html

    def test_says_the_accounts_are_separate(self, _google):
        """The one thing a user must understand before choosing, since picking
        the other button shows an empty account."""
        assert "separate account" in _signin_html()


def _signin_html() -> str:
    response = web._signin_page(providers.enabled(), "https://example.test")
    return response.body.decode()


class TestDisplayLabelIsNotAnIdentity:
    """The token page shows something recognisable, but `sub` stays the key.
    An email can be reassigned; keying on one would hand the next holder the
    previous owner's memory."""

    def test_the_label_does_not_become_the_user_id(self):
        cookie = web._new_session("google:12345", "someone@example.com (Google)")
        request = _FakeRequest({web.SESSION_COOKIE: cookie})
        assert web._session_user(request) == "google:12345"
        assert web._session_display(request) == "someone@example.com (Google)"

    def test_editing_the_label_invalidates_the_session(self):
        """Otherwise a label is a free-text field inside a trusted cookie."""
        cookie = web._new_session("google:12345", "me@example.com")
        forged = cookie.replace("me@example.com", "admin@example.com")
        assert web._session_user(_FakeRequest({web.SESSION_COOKIE: forged})) is None

    def test_a_provider_without_a_label_falls_back_to_the_id(self):
        """A userinfo response missing the field must not render an empty page
        header — the account still has to be named."""
        cookie = web._new_session("github:7")
        assert web._session_display(_FakeRequest({web.SESSION_COOKIE: cookie})) == (
            "github:7"
        )

    def test_an_expired_session_yields_no_label(self):
        expired = web._sign(
            json.dumps(
                {
                    "sub": "google:1",
                    "name": "me@example.com",
                    "exp": int(time.time()) - 1,
                }
            )
        )
        assert web._session_display(_FakeRequest({web.SESSION_COOKIE: expired})) is None


class TestTheLabelReachesThePage:
    def test_the_page_names_the_account_and_provider(self):
        body = web._tokens_page(
            [], "someone@example.com (Google)", "csrf", "https://e.test"
        ).body.decode()
        assert "someone@example.com (Google)" in body

    def test_the_label_is_escaped(self):
        """It comes from the provider, so the page must not trust its shape."""
        body = web._tokens_page(
            [], "<script>x</script> (Google)", "csrf", "https://e.test"
        ).body.decode()
        assert "<script>x</script>" not in body
        assert "&lt;script&gt;" in body


class _FakeRequest:
    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies
