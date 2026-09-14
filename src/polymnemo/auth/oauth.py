"""GitHub OAuth auth — self-provisioning identity, with bearer keys as fallback.

``GitHubOAuthProvider`` verifies tokens at the transport layer (#83);
``TokenSubjectAuth`` reads that verified identity through polymnemo's ``Auth``
seam, so the tools don't change. Both schemes coexist: whichever path a caller
took, the ``user_id`` arrives as ``AccessToken.subject``.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse, urlunparse

from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.dependencies import AccessToken, get_access_token
from key_value.aio.stores.postgresql import PostgreSQLStore

from .base import AuthError

# Created by scripts/schema.sql; shape must match what py-key-value-aio expects.
OAUTH_KV_TABLE = "oauth_kv"
# Marks a token that came from the static key table rather than OAuth.
BEARER_CLIENT_ID = "static-bearer"


class GitHubOAuthProvider(GitHubProvider):
    """GitHub OAuth, plus the static bearer-key table as a fallback.

    ``FastMCP(auth=...)`` enforces at the transport layer, so a static key would
    401 before reaching any tool. ``verify_token`` is the one seam where both
    schemes can live, hence the only override.
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

    Ignores ``headers``: re-parsing the credential here would trust it twice.
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
    """Neon's DIRECT endpoint for a pooled DSN — strip ``-pooler`` from the HOST.

    asyncpg prepares statements per connection while PgBouncer swaps backends per
    transaction, so they go missing intermittently — the trap ``postgres.py``
    avoids with ``prepare_threshold=None``. The asyncpg equivalent,
    ``statement_cache_size``, can't be reached through py-key-value-aio's URL
    path, so bypass the pooler instead. Unchanged if the host has no ``-pooler``.

    Host only: substituting across the DSN would hit a password containing
    ``-pooler.`` first, breaking the credential AND leaving the host pooled.
    Credentials pass through verbatim because urlparse percent-decodes them.
    """
    parsed = urlparse(dsn)
    # userinfo must percent-encode "@", so the last one starts host:port.
    userinfo, _, hostport = parsed.netloc.rpartition("@")
    if "-pooler." not in hostport:
        return dsn
    hostport = hostport.replace("-pooler.", ".", 1)
    netloc = f"{userinfo}@{hostport}" if userinfo else hostport
    return urlunparse(parsed._replace(netloc=netloc))


def _build_client_storage(database_url: str | None) -> PostgreSQLStore | None:
    """Shared storage for the OAuth flow state, or None to let FastMCP fall back
    to its local-filesystem default (fine for single-process dev).

    ``auto_create=False`` because the table is a deploy step, not runtime DDL.
    """
    if not database_url:
        return None
    return PostgreSQLStore(
        url=direct_dsn(database_url),
        table_name=OAUTH_KV_TABLE,
        auto_create=False,
    )
