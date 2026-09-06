# Project context

**polymnemo** — a provider-agnostic, cross-LLM shared long-term memory exposed as an **MCP server**.

- **Stack**: Python 3.11+, FastMCP (Streamable HTTP at `/mcp`), fastembed (local ONNX embeddings), pydantic-settings. Postgres + pgvector (Neon) is the production store; an in-memory store backs local dev/tests.
- **Deploy**: stateless container on Cloud Run; all state in Neon.
- **Principles**: plain text is the single source of truth; **zero external / generative-LLM calls** (embeddings run locally, deterministically); three pluggable layers — **Auth / Store / Retriever** — assembled in `context.build_context()`.

## Architecture conventions

- `src/polymnemo/` layout:
  - `auth/` — `Auth` protocol + `BearerKeyAuth` (per-user `api_key -> user_id`) and a dev `StaticAuth`.
  - `store/` — `Store` protocol + `InMemoryStore` (dev) / `PostgresStore` (prod, pgvector).
  - `retriever/` — `Retriever` protocol + `VectorRetriever` (embeds query, delegates NN to the store).
  - `embedding/` — `Embedder` protocol + `FastEmbedEmbedder` (real) / `StubEmbedder` (offline dev).
  - `service.py` — `MemoryService`: business logic (chunk → embed → persist); tools stay thin.
  - `server.py` — FastMCP tools; `_current_user()` authenticates from request headers.
  - `context.py` — composition root (frozen dataclass); selects implementations by config.
- **Deliberate patterns — do not suggest changing:**
  - Layers are `typing.Protocol`s; implementations intentionally don't inherit them (structural typing for pluggability).
  - The server owns embedding; the same local model is used for reads and writes (consistent vector space). Do not propose calling an external/generative LLM for embeddings or "memory extraction".
  - Bounded results with `limit`/`cursor`; judgment (enough? page more?) is left to the client — don't suggest server-side "smart" truncation.
  - Chunking is sized in **tokens** to fit the model's context window; keep it token-aware.
- **Known / accepted for now (don't flag):**
  - `StaticAuth`, `InMemoryStore`, `StubEmbedder` are dev-only placeholders selected by config.
  - A benign fastembed mean-pooling `UserWarning` on model load.

## Code review guidance

Grade findings by severity; only make **blocking** comments for Critical / High.

### Critical (must fix)
- Crashes, data loss, or security issues.
- Leaking one user's memories to another: any store/retriever path not scoped by `user_id` (and usually `namespace`).
- Logging or returning API keys / bearer tokens.
- Embedding-dimension mismatches vs `POLYMNEMO_EMBED_DIM` / the DB `vector(N)` schema.

### High (strongly suggested)
- Missing or swallowed error handling; unclear errors surfaced to the LLM (tools should raise actionable `ToolError`s).
- Chunks that can exceed the embedding model's token cap (silent truncation).
- Connection handling that would exhaust Postgres connections (must use Neon's pooled connection string).
- Breaking the MCP tool contract (tool signature/return shape vs docstring/schema).

### Medium / Low
- Naming, readability, duplication — only when the same issue appears 3+ times in one file.

## Do not
- Don't comment on pure formatting — a formatter handles it.
- Don't suggest adding comments unless logic is genuinely non-obvious.
- Don't emit filler "looks good" praise to pad the review.
- Don't repeat what CI already catches (lint, type checks, failing tests).
- Don't propose heavyweight dependencies (e.g. langchain, torch) — the project deliberately stays light.

## Ignore paths
- `**/*.lock`, `uv.lock`
- `.github/**` generated workflow scaffolding
- test snapshots / fixtures
