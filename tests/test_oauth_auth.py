"""GitHub OAuth auth (#83): the bearer fallback, and the identity bridge.

The coexistence is the point: if `verify_token` stopped falling back to the
static key table, every non-OAuth client would 401 and nothing else would catch
it.
"""

from __future__ import annotations

import pytest
from fastmcp.server.auth.providers.github import GitHubProvider
from pydantic import ValidationError

from polymnemo.auth import AuthError, TokenSubjectAuth
from polymnemo.auth.oauth import (
    BEARER_CLIENT_ID,
    GitHubOAuthProvider,
    _build_client_storage,
    direct_dsn,
)
from polymnemo.config import Settings


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
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        token = await provider.verify_token("sk-alice")
        assert token is not None
        assert token.subject == "alice"
        assert token.client_id == BEARER_CLIENT_ID

    async def test_synthesized_token_carries_required_scopes(
        self, provider, monkeypatch
    ):
        """Reached production: the transport enforces required_scopes *after*
        verify_token returns, so a token with none gets insufficient_scope and
        every bearer caller is locked out. Asserting only the return value —
        as the other tests here do — cannot see that."""
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        token = await provider.verify_token("sk-alice")
        assert set(provider.required_scopes or []) <= set(token.scopes)

    async def test_unknown_token_is_rejected(self, provider, monkeypatch):
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        # None is what makes FastMCP answer 401 — not an exception.
        assert await provider.verify_token("sk-nope") is None

    async def test_oauth_wins_when_upstream_recognises_the_token(
        self, provider, monkeypatch
    ):
        """A GitHub token must not be shadowed by the static table."""
        from fastmcp.server.dependencies import AccessToken

        async def _oauth_ok(self, token: str):
            return AccessToken(
                token=token, client_id="github", scopes=[], subject="12345"
            )

        monkeypatch.setattr(GitHubProvider, "verify_token", _oauth_ok)
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
        """Prefixing these would orphan every memory written before OAuth."""
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
    """The OAuth store bypasses PgBouncer; asyncpg's statement cache can't be
    turned off through py-key-value-aio's URL path."""

    def test_pooler_infix_is_stripped(self):
        assert direct_dsn(
            "postgresql://u:p@ep-x-123-pooler.c-3.us-west-2.aws.neon.tech/db?sslmode=require"
        ) == (
            "postgresql://u:p@ep-x-123.c-3.us-west-2.aws.neon.tech/db?sslmode=require"
        )

    def test_non_pooled_dsn_is_untouched(self):
        dsn = "postgresql://u:p@localhost:5432/db"
        assert direct_dsn(dsn) == dsn

    def test_password_containing_the_infix_is_not_corrupted(self):
        """The whole-string substitution this replaced hit the password first,
        breaking the credential and leaving the host pooled."""
        out = direct_dsn("postgresql://u:pw-pooler.x@ep-a-pooler.neon.tech/db")
        assert out == "postgresql://u:pw-pooler.x@ep-a.neon.tech/db"

    def test_percent_encoded_password_is_passed_through(self):
        """Rebuilding netloc from urlparse's decoded parts would turn %40 into
        @ and break the DSN."""
        out = direct_dsn("postgresql://u:p%40ss@ep-a-pooler.neon.tech/db")
        assert "p%40ss" in out


class TestClientStorage:
    def test_no_database_means_no_shared_store(self):
        """Dev without Postgres falls back to FastMCP's local default."""
        assert _build_client_storage(None) is None
        assert _build_client_storage("") is None

    def test_configured_store_does_not_auto_create(self):
        """The table is a deploy step, so a missing one must fail loudly."""
        store = _build_client_storage("postgresql://u:p@host/db")
        assert store is not None
        assert store._auto_create is False
        assert store._table_name == "oauth_kv"


class TestAuthConfig:
    def test_static_auth_with_oauth_is_rejected(self):
        """Left unguarded, the transport would enforce OAuth while StaticAuth
        returned one user_id for everyone through it."""
        with pytest.raises(ValidationError, match="incompatible with OAuth"):
            Settings(
                auth_backend="static",
                oauth_client_id="id",
                oauth_client_secret="secret",
                oauth_base_url="https://example.test",
            )

    def test_static_auth_without_oauth_is_fine(self):
        assert Settings(auth_backend="static").auth_backend == "static"

    def test_oauth_needs_all_three_settings(self):
        # auth_backend is explicit because conftest sets it to "static" for the
        # suite, which _check_auth rightly refuses to combine with OAuth.
        assert not Settings(auth_backend="bearer", oauth_client_id="id").oauth_enabled
        assert Settings(
            auth_backend="bearer",
            oauth_client_id="id",
            oauth_client_secret="secret",
            oauth_base_url="https://example.test",
        ).oauth_enabled


class TestAllowedRedirectUris:
    """Extra patterns extend the localhost floor; they never replace it.

    auth_backend is explicit throughout: conftest sets it to "static" for the
    suite, so a runner that also had the OAuth credentials set would trip
    _check_auth and fail these with an error about something else entirely.
    """

    def test_empty_by_default(self):
        assert Settings(auth_backend="bearer").parse_allowed_redirect_uris() == []

    def test_parsed_and_trimmed(self):
        s = Settings(
            auth_backend="bearer",
            oauth_allowed_redirect_uris=" https://a.test/cb , https://b.test/* ",
        )
        assert s.parse_allowed_redirect_uris() == [
            "https://a.test/cb",
            "https://b.test/*",
        ]

    def test_malformed_patterns_are_rejected(self):
        """A bad pattern fails closed — it matches nothing — so the operator
        would otherwise learn about it from a user who cannot log in."""
        for bad in ("htts://typo.test/cb", "https://", "localhost"):
            with pytest.raises(ValidationError, match="not a usable pattern"):
                Settings(auth_backend="bearer", oauth_allowed_redirect_uris=bad)

    def test_wildcard_patterns_are_accepted(self):
        s = Settings(
            auth_backend="bearer",
            oauth_allowed_redirect_uris="https://*.example.com/*",
        )
        assert s.parse_allowed_redirect_uris() == ["https://*.example.com/*"]

    def test_localhost_floor_survives_extras(self):
        from fastmcp.server.auth.redirect_validation import (
            DEFAULT_LOCALHOST_PATTERNS,
            validate_redirect_uri,
        )

        allowed = (
            DEFAULT_LOCALHOST_PATTERNS
            + Settings(
                oauth_allowed_redirect_uris="https://hosted.test/cb"
            ).parse_allowed_redirect_uris()
        )
        assert validate_redirect_uri("http://localhost:33418/cb", allowed)
        assert validate_redirect_uri("https://hosted.test/cb", allowed)
        assert not validate_redirect_uri("https://attacker.test/cb", allowed)


class TestPrefixGate:
    """A token without the `pmn_` prefix cannot be one of ours, so it must not
    cost a hash and a database round-trip."""

    class _CountingStore:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def resolve(self, token: str) -> str | None:
            self.calls.append(token)
            return None

    def _provider(self, store):
        return GitHubOAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            base_url="https://example.test",
            token_store=store,
        )

    async def test_token_without_the_prefix_never_reaches_the_store(self, monkeypatch):
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        store = self._CountingStore()
        assert await self._provider(store).verify_token("random-garbage") is None
        assert store.calls == []

    async def test_token_with_the_prefix_is_looked_up(self, monkeypatch):
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        store = self._CountingStore()
        assert await self._provider(store).verify_token("pmn_whatever") is None
        assert store.calls == ["pmn_whatever"]


class TestEnginePropertyIsPublic:
    def test_postgres_store_exposes_engine(self):
        """`_token_store()` reads `.engine`; if that became private again the
        lookup would return None and tokens would quietly stop working."""
        from polymnemo.store.postgres import PostgresStore

        assert isinstance(PostgresStore.engine, property)
