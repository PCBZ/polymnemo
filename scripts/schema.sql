-- polymnemo schema — Postgres + pgvector.
--
-- Apply once to your database (Neon):
--   psql "$POLYMNEMO_DATABASE_URL" -f scripts/schema.sql
--
-- The embedding dimension (384) MUST match POLYMNEMO_EMBED_DIM / the model.
-- Changing the model's dimension means recreating the column and re-embedding.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   VECTOR(384) NOT NULL,
    tags        TEXT[] NOT NULL DEFAULT '{}',
    source      TEXT,
    session_id  TEXT,        -- set for chunks of a saved session (#15)
    seq         INTEGER,     -- 0-based order within a session
    kind         TEXT NOT NULL DEFAULT 'text',  -- text | file | image | video (#44)
    object_key   TEXT,        -- pointer into object storage (media memories)
    content_type TEXT,
    size_bytes   BIGINT,
    checksum     TEXT,
    confirmed    BOOLEAN NOT NULL DEFAULT TRUE,  -- media hidden until upload confirmed (#50)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Scoping: reads filter by namespace (+ user_id for private namespaces),
-- writes filter by (id, user_id).
CREATE INDEX IF NOT EXISTS memories_user_namespace_idx
    ON memories (user_id, namespace);
CREATE INDEX IF NOT EXISTS memories_namespace_idx
    ON memories (namespace);
-- Reassemble a session in order.
CREATE INDEX IF NOT EXISTS memories_session_idx
    ON memories (user_id, session_id, seq);

-- Approximate nearest-neighbour on cosine distance (matches the retriever).
CREATE INDEX IF NOT EXISTS memories_embedding_hnsw_idx
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Per-user bearer keys: {api_key -> user_id}.
CREATE TABLE IF NOT EXISTS api_keys (
    api_key  TEXT PRIMARY KEY,
    user_id  TEXT NOT NULL
);
