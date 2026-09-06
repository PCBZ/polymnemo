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
    # Large content is split on write so recall always returns "N small things".
    chunk_size: int = 1000
    chunk_overlap: int = 100

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
