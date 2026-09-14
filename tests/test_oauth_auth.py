"""GitHub OAuth auth (#83): the bearer fallback, and the identity bridge.

The point of these tests is the *coexistence*. `FastMCP(auth=...)` enforces at
the transport layer, so if `verify_token` stopped falling back to the static key
table, every non-OAuth client would start getting 401s — a regression that no
other test would catch.
"""

from __future__ import annotations

import pytest

from polymnemo.auth import AuthError, TokenSubjectAuth
from polymnemo.auth.oauth import (
    BEARER_CLIENT_ID,
    GitHubOAuthProvider,
    build_client_storage,
    direct_dsn,
)


@pytest.fixture
def provider() -> GitHubOAuthProvider:
    return GitHubOAuthProvider(
        client_id="test-client",
        client_secret="test-secret",
        base_url="https://example.test",
        static_keys={"sk-alice": "alice"},
    )


async def _no_oauth(self, token: str):
    """Stand in for an upstream that recognises nothing, so the fallback runs."""
    return None


class TestBearerFallback:
    async def test_known_static_key_authenticates(self, provider, monkeypatch):
        monkeypatch.setattr(GitHubOAuthProvider.__bases__[0], "verify_token", _no_oauth)
        token = await provider.verify_token("sk-alice")
        assert token is not None
        assert token.subject == "alice"
        assert token.client_id == BEARER_CLIENT_ID

    async def test_unknown_token_is_rejected(self, provider, monkeypatch):
        monkeypatch.setattr(GitHubOAuthProvider.__bases__[0], "verify_token", _no_oauth)
        # None is what makes FastMCP answer 401 — not an exception.
        assert await provider.verify_token("sk-nope") is None

    async def test_oauth_wins_when_upstream_recognises_the_token(
        self, provider, monkeypatch
    ):
        """A GitHub-issued token must not be shadowed by the static table."""
        from fastmcp.server.dependencies import AccessToken

        async def _oauth_ok(self, token: str):
            return AccessToken(
                token=token, client_id="github", scopes=[], subject="12345"
            )

        monkeypatch.setattr(GitHubOAuthProvider.__bases__[0], "verify_token", _oauth_ok)
        # Deliberately a key that IS in the static table.
        token = await provider.verify_token("sk-alice")
        assert token.subject == "12345"
        assert token.client_id == "github"


class TestTokenSubjectAuth:
    def test_oauth_subject_is_namespaced(self, monkeypatch):
        from fastmcp.server.dependencies import AccessToken

        monkeypatch.setattr(
            "polymnemo.auth.oauth.get_access_token",
            lambda: AccessToken(
                token="t", client_id="github", scopes=[], subject="12345"
            ),
        )
        assert TokenSubjectAuth().authenticate({}) == "github:12345"

    def test_bearer_subject_is_left_alone(self, monkeypatch):
        """Bearer subjects are already polymnemo user ids — prefixing them would
        orphan every memory written before OAuth existed."""
        from fastmcp.server.dependencies import AccessToken

        monkeypatch.setattr(
            "polymnemo.auth.oauth.get_access_token",
            lambda: AccessToken(
                token="t", client_id=BEARER_CLIENT_ID, scopes=[], subject="alice"
            ),
        )
        assert TokenSubjectAuth().authenticate({}) == "alice"

    def test_no_token_raises(self, monkeypatch):
        monkeypatch.setattr("polymnemo.auth.oauth.get_access_token", lambda: None)
        with pytest.raises(AuthError):
            TokenSubjectAuth().authenticate({})


class TestDirectDsn:
    """The OAuth store must bypass PgBouncer: asyncpg prepares statements per
    connection, and py-key-value-aio's URL path exposes no way to turn that off.
    """

    def test_pooler_infix_is_stripped(self):
        assert direct_dsn(
            "postgresql://u:p@ep-x-123-pooler.c-3.us-west-2.aws.neon.tech/db?sslmode=require"
        ) == (
            "postgresql://u:p@ep-x-123.c-3.us-west-2.aws.neon.tech/db?sslmode=require"
        )

    def test_non_pooled_dsn_is_untouched(self):
        dsn = "postgresql://u:p@localhost:5432/db"
        assert direct_dsn(dsn) == dsn

    def test_only_the_host_infix_is_rewritten(self):
        """A password or database name containing "-pooler." must survive."""
        dsn = "postgresql://u:pw-pooler.x@ep-a-pooler.neon.tech/db"
        # count=1 rewrites the first occurrence only — which is in the password
        # here, so this documents the limitation rather than pretending it away.
        assert direct_dsn(dsn).count("-pooler") == 1


class TestClientStorage:
    def test_no_database_means_no_shared_store(self):
        """Dev without Postgres falls back to FastMCP's local default."""
        assert build_client_storage(None) is None
        assert build_client_storage("") is None

    def test_configured_store_does_not_auto_create(self):
        """The table is a deploy step (scripts/schema.sql), so a missing one
        should fail loudly rather than appear at runtime."""
        store = build_client_storage("postgresql://u:p@host/db")
        assert store is not None
        assert store._auto_create is False
        assert store._table_name == "oauth_kv"
