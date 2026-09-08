"""Runtime configuration.

Sourced from environment variables (prefix ``POLYMNEMO_``) and an optional
``.env`` file, via pydantic-settings — it handles type coercion, defaults, and
empty-value fallback declaratively.

Scope for Phase 0 #1: HTTP transport plus the embedding/chunking knobs the
skeleton carries. Later issues extend this (database URL in #2/#6, API keys in
#5, namespaces/limits in Phase 1).
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POLYMNEMO_",  # POLYMNEMO_HOST, POLYMNEMO_MCP_PATH, ...
        env_file=".env",
        env_ignore_empty=True,  # an empty/unset var falls back to the default
        extra="ignore",
    )

    # --- HTTP transport ------------------------------------------------------
    host: str = "127.0.0.1"
    # Prefer POLYMNEMO_PORT; fall back to Cloud Run's injected PORT; then 8000.
    port: int = Field(8000, validation_alias=AliasChoices("POLYMNEMO_PORT", "PORT"))
    mcp_path: str = "/mcp"

    # --- Storage -------------------------------------------------------------
    # When set, the Postgres (Neon + pgvector) store is used; otherwise the
    # in-memory store (dev/tests). On Neon use the POOLED connection string
    # (PgBouncer) so Cloud Run's short-lived connections don't exhaust the DB.
    database_url: str | None = Field(
        None, validation_alias=AliasChoices("POLYMNEMO_DATABASE_URL", "DATABASE_URL")
    )
    # Fail fast instead of silently using the in-memory store when no database_url
    # is set. Enabled in the production image so a misconfigured deploy doesn't
    # quietly lose memories.
    require_database: bool = False

    # --- Embeddings ----------------------------------------------------------
    # A multilingual model keeps Chinese / cross-language recall working out of
    # the box. The dimension is pinned here (and, later, into the DB schema), so
    # it must match the model: changing the model means re-embedding everything.
    # (paraphrase-multilingual-MiniLM-L12-v2 is fastembed's multilingual 384-dim
    # option; intfloat/multilingual-e5-small is NOT in fastembed's model list.)
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_dim: int = 384
    # Which embedder to wire: "fastembed" (real ONNX model) or "stub"
    # (dependency-free hashed bag-of-words, for offline dev / tests).
    embed_backend: str = "fastembed"

    # --- Chunking ------------------------------------------------------------
    # Split on write so recall returns "N small things". Sized in *tokens* to fit
    # the model's context window (kept under the 128-token cap of the default
    # model), so a chunk's tail is never truncated out of its embedding.
    chunk_tokens: int = 120
    chunk_overlap_tokens: int = 20

    # --- Namespaces ----------------------------------------------------------
    # Default collection when a tool call omits one.
    default_namespace: str = "shared"
    # Comma-separated namespaces whose reads are visible to every user ("born
    # shared"); any other namespace is private to its owner. Writes are always
    # owner-scoped.
    shared_namespaces: str = "shared"
    # Namespace saved sessions land in when a tool omits one. Kept out of
    # shared_namespaces so a session (a full transcript) stays private to its
    # owner — otherwise its verbatim chunks would be world-readable via recall.
    session_namespace: str = "sessions"

    def parse_shared_namespaces(self) -> frozenset[str]:
        return frozenset(n.strip() for n in self.shared_namespaces.split(",") if n.strip())

    # --- Recall / list -------------------------------------------------------
    # Default page sizes; the client decides whether to page further.
    recall_limit: int = 8
    list_limit: int = 20

    # --- Rate limiting -------------------------------------------------------
    # One global (per-process) token bucket via pyrate-limiter, off by default.
    # Not per-user — just caps this instance's overall intake, in ops per minute.
    ratelimit_enabled: bool = False
    ratelimit_per_min: int = 600

    # --- Auth ----------------------------------------------------------------
    # "bearer" (per-user keys, the real scheme) or "static" (dev, single user).
    auth_backend: str = "bearer"
    # Per-user keys as "key1:alice,key2:bob" (env POLYMNEMO_API_KEYS).
    api_keys: str = ""

    def parse_api_keys(self) -> dict[str, str]:
        """Parse ``api_keys`` into an ``{api_key: user_id}`` map."""
        out: dict[str, str] = {}
        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            key, _, user_id = pair.partition(":")
            key, user_id = key.strip(), user_id.strip()
            if key and user_id:
                out[key] = user_id
        return out


settings = Settings()
