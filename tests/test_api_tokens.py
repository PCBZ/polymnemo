"""Self-service API tokens (#125).

The database-backed tests are gated on TEST_DATABASE_URL, like the store tests.
Everything else runs offline, including the auth chain — a stub store is enough
to prove the order of OAuth -> env keys -> database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.server.auth.providers.github import GitHubProvider

from polymnemo.auth.oauth import BEARER_CLIENT_ID, GitHubOAuthProvider
from polymnemo.auth.tokens import (
    TOKEN_PREFIX,
    ApiTokenStore,
    generate_token,
    hash_token,
)


class TestTokenPrimitives:
    def test_tokens_are_prefixed_and_unique(self):
        """The prefix is what makes a leaked token identifiable in a log or by a
        secret scanner."""
        tokens = {generate_token() for _ in range(50)}
        assert len(tokens) == 50
        assert all(t.startswith(TOKEN_PREFIX) for t in tokens)

    def test_hash_is_stable_and_not_the_token(self):
        token = generate_token()
        assert hash_token(token) == hash_token(token)
        assert token not in hash_token(token)
        assert len(hash_token(token)) == 64  # sha256 hex

    def test_different_tokens_hash_differently(self):
        assert hash_token(generate_token()) != hash_token(generate_token())


class _StubTokenStore:
    """Just the one method the auth chain calls."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def resolve(self, token: str) -> str | None:
        self.calls.append(token)
        return self._mapping.get(token)


async def _no_oauth(self, token: str):
    return None


@pytest.fixture
def provider() -> GitHubOAuthProvider:
    return GitHubOAuthProvider(
        client_id="test-client",
        client_secret="test-secret",
        base_url="https://example.test",
        static_keys={"sk-env": "env-user"},
        token_store=_StubTokenStore({"pmn_db": "db-user"}),
    )


class TestAuthChain:
    async def test_database_token_authenticates(self, provider, monkeypatch):
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        token = await provider.verify_token("pmn_db")
        assert token is not None
        assert token.subject == "db-user"
        assert token.client_id == BEARER_CLIENT_ID

    async def test_env_keys_are_checked_before_the_database(
        self, provider, monkeypatch
    ):
        """The env keys are the escape hatch, so they must not depend on the
        database being reachable — which means never querying it first."""
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        token = await provider.verify_token("sk-env")
        assert token.subject == "env-user"
        assert provider._token_store.calls == []  # never consulted

    async def test_unknown_token_is_rejected(self, provider, monkeypatch):
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        assert await provider.verify_token("pmn_nope") is None

    async def test_database_token_carries_required_scopes(self, provider, monkeypatch):
        """Same trap as #123: the transport enforces required_scopes after this
        returns, so a token without them is rejected as insufficient_scope."""
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        token = await provider.verify_token("pmn_db")
        assert set(provider.required_scopes or []) <= set(token.scopes)

    async def test_no_store_configured_is_not_an_error(self, monkeypatch):
        """No database (dev) means tokens simply don't resolve, not a crash."""
        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        p = GitHubOAuthProvider(
            client_id="c",
            client_secret="s",
            base_url="https://example.test",
            static_keys={},
        )
        assert await p.verify_token("pmn_anything") is None


pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL (a Postgres with schema.sql applied)",
)


@pytestmark_db
class TestApiTokenStore:
    @pytest.fixture
    def store(self):
        from sqlalchemy import create_engine, text

        from polymnemo.store.postgres import _sqlalchemy_url

        engine = create_engine(_sqlalchemy_url(os.environ["TEST_DATABASE_URL"]))
        s = ApiTokenStore(engine)

        def _clear():
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM api_tokens WHERE user_id LIKE 'test-%'"))

        _clear()
        yield s
        _clear()

    def test_create_then_resolve(self, store):
        token, meta = store.create("test-alice", "ci")
        assert meta.label == "ci"
        assert store.resolve(token) == "test-alice"

    def test_token_is_not_stored_in_the_clear(self, store):
        """A leak of the table must not yield usable credentials."""
        from sqlalchemy import text

        token, _ = store.create("test-alice", "ci")
        with store._engine.begin() as conn:
            rows = conn.execute(
                text("SELECT token_hash FROM api_tokens WHERE user_id = 'test-alice'")
            ).all()
        assert all(token not in r[0] for r in rows)
        assert rows[0][0] == hash_token(token)

    def test_expired_token_does_not_resolve(self, store):
        token, _ = store.create("test-alice", "short", expires_in_days=1)
        from sqlalchemy import text

        with store._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE api_tokens SET expires_at = :t WHERE user_id = 'test-alice'"
                ),
                {"t": datetime.now(UTC) - timedelta(minutes=1)},
            )
        assert store.resolve(token) is None

    def test_revoke_is_owner_scoped(self, store):
        """Guessing an id must not let one user revoke another's token."""
        token, meta = store.create("test-alice", "ci")
        assert store.revoke("test-bob", meta.id) is False
        assert store.resolve(token) == "test-alice"
        assert store.revoke("test-alice", meta.id) is True
        assert store.resolve(token) is None

    def test_list_excludes_other_users_and_the_token(self, store):
        store.create("test-alice", "a1")
        store.create("test-bob", "b1")
        items = store.list_for_user("test-alice")
        assert [t.label for t in items] == ["a1"]
        assert not hasattr(items[0], "token")

    def test_zero_days_is_not_treated_as_never(self, store):
        """Truthiness would read 0 as "no expiry". The web layer clamps to >= 1,
        but a direct caller would hit the inversion silently."""
        _, meta = store.create("alice", "zero", expires_in_days=0)
        assert meta.expires_at is not None
