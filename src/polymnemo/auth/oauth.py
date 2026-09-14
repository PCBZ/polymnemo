"""GitHub OAuth auth — self-provisioning identity, with bearer keys as fallback.

``BearerKeyAuth`` requires the maintainer to hand-edit a secret and redeploy for
every new user (#83). OAuth removes that: a caller logs in with GitHub, FastMCP
verifies the token, and the stable ``sub`` becomes the ``user_id``. There is no
user table — the identity provider is the user database.

Two pieces, because FastMCP and polymnemo each own one half of auth:

- ``GitHubOAuthProvider`` plugs into ``FastMCP(auth=...)`` and *verifies* tokens
  at the transport layer.
- ``TokenSubjectAuth`` implements polymnemo's ``Auth`` seam and *reads* the
  already-verified identity, so ``current_user()`` and the tools don't change.

Both schemes coexist by design: ``verify_token`` tries OAuth first and falls
back to the static key table, so CI and clients with weak OAuth support keep
working. Whichever path a caller took, the ``user_id`` arrives through one
field — ``AccessToken.subject``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.dependencies import AccessToken, get_access_token
from key_value.aio.stores.postgresql import PostgreSQLStore

from .base import AuthError

# Created by scripts/schema.sql, like every other table. Must match the shape
# py-key-value-aio expects.
OAUTH_KV_TABLE = "oauth_kv"

# Marks a token that authenticated via the static key table rather than OAuth,
# so logs and debugging can tell the two apart.
BEARER_CLIENT_ID = "static-bearer"


class GitHubOAuthProvider(GitHubProvider):
    """GitHub OAuth, plus the static bearer-key table as a fallback.

    ``FastMCP(auth=...)`` enforces at the transport layer: without this
    subclass a static key would be rejected with 401 before reaching any tool,
    which would break every non-OAuth client. ``verify_token`` is the single
    seam where both schemes can live, so it is the only thing overridden.
    """

    def __init__(self, *args, static_keys: Mapping[str, str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        # {api_key -> user_id}; empty means OAuth is the only way in.
        self._static_keys = dict(static_keys or {})

    async def verify_token(self, token: str) -> AccessToken | None:
        oauth = await super().verify_token(token)
        if oauth is not None:
            return oauth
        user_id = self._static_keys.get(token)
        if user_id is None:
            return None  # neither scheme recognises it -> 401
        return AccessToken(
            token=token,
            client_id=BEARER_CLIENT_ID,
            scopes=[],
            subject=user_id,
            claims={"scheme": "bearer"},
        )


class TokenSubjectAuth:
    """Resolve ``user_id`` from the token FastMCP already verified.

    Implements the ``Auth`` Protocol but ignores ``headers``: by the time a tool
    runs, the transport layer has verified the credential and stashed it in the
    request context. Re-parsing the header here would mean trusting it twice.
    """

    def __init__(self, provider_prefix: str = "github") -> None:
        self._prefix = provider_prefix

    def authenticate(self, headers: Mapping[str, str]) -> str:
        token = get_access_token()
        if token is None or not token.subject:
            raise AuthError("Not authenticated")
        # Bearer subjects are already polymnemo user ids; only OAuth subjects
        # need namespacing, so a GitHub `sub` can't collide with a chosen name.
        if token.client_id == BEARER_CLIENT_ID:
            return token.subject
        return f"{self._prefix}:{token.subject}"


def direct_dsn(dsn: str) -> str:
    """Neon's DIRECT endpoint for a pooled DSN — strip the ``-pooler`` infix.

    The app talks to Neon through PgBouncer in transaction mode, which is right
    for short web requests but wrong for asyncpg: asyncpg prepares statements
    per connection, and PgBouncer hands out a different backend per transaction,
    so a prepared statement goes missing intermittently. ``postgres.py`` dodges
    this for psycopg with ``prepare_threshold=None``; the equivalent knob here is
    ``statement_cache_size``, which py-key-value-aio's URL path gives us no way
    to set (and asyncpg silently ignores it as a DSN parameter — verified).

    Bypassing the pooler avoids the problem outright, and this store's traffic is
    a handful of rows per login, so it doesn't need PgBouncer's multiplexing.
    A DSN with no ``-pooler`` is returned unchanged.
    """
    return re.sub(r"-pooler(\.)", r"\1", dsn, count=1)


def build_client_storage(database_url: str | None) -> PostgreSQLStore | None:
    """Shared storage for the OAuth proxy's flow state, or None to let FastMCP
    fall back to its local-filesystem default (fine for single-process dev).

    ``auto_create=False``: the table is a deploy step (scripts/schema.sql), so a
    missing one should fail loudly rather than be conjured at runtime.
    """
    if not database_url:
        return None
    return PostgreSQLStore(
        url=direct_dsn(database_url),
        table_name=OAUTH_KV_TABLE,
        auto_create=False,
    )
