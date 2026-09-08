# polymnemo

**A shared long-term memory across any LLM, over [MCP](https://modelcontextprotocol.io).**

One memory store, many models. Point Claude Desktop, an MCP-capable IDE, or any
other [Model Context Protocol](https://modelcontextprotocol.io) client at the same
polymnemo endpoint and they read and write the **same** memories — because the
memory lives in *your* Postgres, not inside any one model. Store a fact with Claude
today, recall it from a different assistant tomorrow.

> **Status:** early development. The MVP (semantic memory + durable pgvector store)
> works; launch hardening is in progress. See the
> [wiki](https://github.com/PCBZ/polymnemo/wiki) for the plan and
> [issues](https://github.com/PCBZ/polymnemo/issues) for progress.

---

## Why polymnemo (and why it's not a thin wrapper)

- **Plain text is the source of truth.** Memories are stored verbatim. Retrieval
  returns exactly what you wrote — nothing is paraphrased, summarized, or
  hallucinated on the way in or out.
- **Zero generative-LLM calls.** The server never calls GPT/Claude/etc. to
  "process" your memories. Writing and reading are deterministic: chunk → embed →
  store, and query → embed → nearest-neighbour. No token bills, no non-determinism,
  no data handed to a model provider.
- **Local embeddings.** Vectors are produced on-box with a small multilingual ONNX
  model ([fastembed](https://github.com/qdrant/fastembed)) — no embedding API key,
  and Chinese ↔ English cross-language recall works out of the box.
- **Three pluggable layers.** Auth, Store, and Retriever are each a `typing.Protocol`
  with swappable implementations, wired once in a composition root. Swap the DB or
  the ranking strategy without touching the tools.
- **Provider-agnostic sharing.** It's an MCP *service*, not a framework or an agent.
  Any MCP client of any vendor can share the same memory, scoped per user, with
  explicit shared-vs-private namespaces.

## Architecture

```mermaid
flowchart TD
    subgraph clients["MCP clients (any vendor)"]
        C1["Claude Desktop"]
        C2["IDE / other LLM"]
        C3["MCP Inspector"]
    end

    subgraph server["polymnemo (FastMCP server)"]
        S["Tools<br/>remember · recall · list · get<br/>update · forget · save/load_session"]
        SVC["MemoryService<br/>(chunk · embed · page · defaults)"]
        subgraph layers["Pluggable layers (AppContext)"]
            A["Auth<br/>BearerKeyAuth"]
            R["Retriever<br/>VectorRetriever"]
            E["Embedder<br/>fastembed (local ONNX)"]
            ST["Store<br/>PostgresStore"]
        end
    end

    DB[("Postgres + pgvector<br/>(Neon)")]

    C1 & C2 & C3 -->|"Streamable HTTP /mcp<br/>Authorization: Bearer &lt;key&gt;"| S
    S --> SVC
    S -.authenticate.-> A
    SVC --> R
    SVC --> E
    SVC --> ST
    R --> ST
    ST -->|"SQLAlchemy + pgvector"| DB
```

- **Transport** — [FastMCP](https://github.com/jlowin/fastmcp) over **Streamable
  HTTP** at `/mcp`. Every call carries `Authorization: Bearer <key>`.
- **Tools** stay thin: authenticate → delegate to `MemoryService` → return; domain
  errors surface as actionable `ToolError` messages, not stack traces.
- **`MemoryService`** owns the logic that isn't transport: chunking, embedding,
  pagination, namespace defaults.
- **Pluggable layers** (`Auth` / `Store` / `Retriever`, plus the `Embedder`) are
  selected from config in one place (`build_context()`), so implementations swap
  without touching call sites.
- **Store** — Postgres + [pgvector](https://github.com/pgvector/pgvector) via
  SQLAlchemy, with an HNSW cosine index. On [Neon](https://neon.tech) use the pooled
  connection string. (A non-durable in-memory store backs local dev / tests.)

## Tools

All tools are per-user: the bearer key resolves to a `user_id`, and writes are
always owner-scoped. Reads see your own memories plus anything in a *shared*
namespace.

| Tool | Arguments | Returns | Hints |
|------|-----------|---------|-------|
| `ping` | — | `{ok, server, version, layers}` | read-only |
| `remember` | `content`, `namespace?`, `tags?`, `source?` | `{ids, chunks, namespace}` | write |
| `recall` | `query`, `namespace?`, `limit=8`, `cursor?` | `{items, total, has_more, next_cursor}` | read-only |
| `list_memories` | `namespace?`, `limit=20`, `cursor?` | `{items, total, has_more, next_cursor}` | read-only |
| `get_memory` | `id` | the memory | read-only |
| `update` | `id`, `content` | the updated memory | write · idempotent |
| `forget` | `id` | `{id, deleted}` | destructive · idempotent |
| `save_session` | `session_id`, `content`, `namespace?` | `{session_id, chunks, chars, namespace}` | write |
| `load_session` | `session_id`, `page=0`, `page_size=8000` | `{session_id, content, page, page_size, total_chars, has_more}` | read-only |

**Write path:** `remember` splits `content` into token-bounded chunks (one vector
each) so large notes become several small, individually-recallable memories.
**Read path:** `recall` embeds the query and returns the nearest chunks by cosine
similarity, bounded by `limit` and paged with `next_cursor`.

**Sessions** (`save_session` / `load_session`) store a full transcript as *ordered,
losslessly-reassemblable* chunks — `load_session` reconstructs it byte-for-byte.
Sessions default to a **private** namespace (`sessions`), so a transcript is never
world-readable even though shared namespaces exist.

### Resource

`memory://{namespace}` exposes a namespace's memories (for the authenticated user)
as an MCP resource, so a client can auto-inject the collection. Same shape as
`list_memories`; page further with that tool.

## Quickstart

The Definition of Done for this doc: **a stranger can configure a key + endpoint
below and use it.** Here's the whole path.

### 1. Install & run the server

Requires **Python 3.11+**. Uses plain `venv` + `pip`.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[postgres]"         # omit [postgres] for in-memory dev only
```

### 2. Provision Postgres (pgvector)

polymnemo's durable store is Postgres + pgvector. The easiest hosted option is
[Neon](https://neon.tech) (has pgvector; use the **pooled** connection string).
Apply the schema once:

```bash
psql "<your-connection-string>" -f scripts/schema.sql
```

### 3. Configure users and the database

Copy `.env.example` to `.env` and set at least the database URL and one API key:

```bash
# .env
POLYMNEMO_DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
POLYMNEMO_AUTH_BACKEND=bearer
POLYMNEMO_API_KEYS=sk-alice-secret:alice,sk-bob-secret:bob   # "key:user_id" pairs
```

Keys map an opaque bearer token to a `user_id`. Per-user keys are required — a
single shared token would make namespaces meaningless. Then run it:

```bash
polymnemo                            # serves Streamable HTTP at http://127.0.0.1:8000/mcp
```

Or with Docker (the image defaults to requiring a database):

```bash
docker build -t polymnemo .
docker run -e POLYMNEMO_DATABASE_URL="..." -e POLYMNEMO_API_KEYS="sk-alice-secret:alice" \
           -e PORT=8080 -p 8080:8080 polymnemo
```

### 4. Connect an MCP client

polymnemo speaks MCP over Streamable HTTP, so any client that supports remote
(HTTP) MCP servers with custom headers can connect. It needs exactly two things:

- **Endpoint:** `http://<host>:<port>/mcp`
- **Header:** `Authorization: Bearer <your-key>`

For clients that read an `mcpServers` config:

```jsonc
{
  "mcpServers": {
    "polymnemo": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer sk-alice-secret" }
    }
  }
}
```

Verify quickly with the official inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP · URL: http://127.0.0.1:8000/mcp
# Header:    Authorization: Bearer sk-alice-secret
# then call `ping`, `remember`, `recall`.
```

## Configuration

All settings are `POLYMNEMO_*` environment variables (or `.env`). Full list with
comments in [.env.example](.env.example); the essentials:

| Variable | Default | Purpose |
|----------|---------|---------|
| `POLYMNEMO_DATABASE_URL` | *(unset)* | Postgres+pgvector DSN. Required in production; unset → in-memory (dev/tests). |
| `POLYMNEMO_REQUIRE_DATABASE` | `false` | Fail fast if no DB URL (the Docker image sets `true`). |
| `POLYMNEMO_AUTH_BACKEND` | `bearer` | `bearer` (per-user keys) or `static` (single dev user). |
| `POLYMNEMO_API_KEYS` | *(empty)* | `"key1:alice,key2:bob"` — required for `bearer`. |
| `POLYMNEMO_EMBED_MODEL` | `…MiniLM-L12-v2` | Multilingual embedding model. |
| `POLYMNEMO_EMBED_DIM` | `384` | Must match the model (pinned into the schema). |
| `POLYMNEMO_EMBED_BACKEND` | `fastembed` | `fastembed` (real) or `stub` (offline). |
| `POLYMNEMO_DEFAULT_NAMESPACE` | `shared` | Namespace when a tool omits one. |
| `POLYMNEMO_SHARED_NAMESPACES` | `shared` | Comma-separated namespaces readable by everyone. |
| `POLYMNEMO_SESSION_NAMESPACE` | `sessions` | Private namespace for saved sessions. |
| `POLYMNEMO_HOST` / `POLYMNEMO_PORT` / `POLYMNEMO_MCP_PATH` | `127.0.0.1` / `8000` / `/mcp` | Transport. |

## How it compares

polymnemo occupies a deliberately narrow niche: a **provider-agnostic, deterministic
memory _service_** that many different LLMs share over MCP. That's different from the
memory frameworks it's often lumped with.

| | polymnemo | [mem0](https://github.com/mem0ai/mem0) | KG memory (e.g. [Zep/Graphiti](https://github.com/getzep/graphiti)) | [Letta](https://github.com/letta-ai/letta) (MemGPT) |
|---|---|---|---|---|
| What it is | Shared memory service over MCP | Memory layer/SDK | Knowledge-graph memory | Agent framework with memory |
| LLM calls to store/organize | **None** (deterministic) | Yes (extracts/summarizes facts) | Yes (entity/relation extraction) | Yes (agent manages its own memory) |
| Truth source | Verbatim plain text | Model-derived facts | Graph of entities/edges | Agent state |
| Embeddings | Local ONNX, no API key | Pluggable (often API) | Pluggable | Pluggable |
| Cross-vendor sharing | **First-class** (any MCP client) | Via its own SDK/API | Via its own API | Within Letta |
| Not a… | framework / agent | — | — | it *is* a framework |

**When polymnemo fits:** you want several different assistants to share one honest,
plain-text memory, with no extra model in the loop and no lock-in to one vendor's
SDK. **When it doesn't:** you want automatic fact extraction, a reasoning graph, or a
full agent runtime — reach for the tools above.

## Development

```bash
pip install -e ".[dev]"
pytest                               # fast, offline (stub embedder, in-memory store)
```

- **Postgres tests** run only when `TEST_DATABASE_URL` points at a pgvector Postgres
  (CI provides one; locally use Docker `pgvector/pgvector:pg16`).
- **Opt-in real-model tests** (download the embedding model / tokenizer):
  `POLYMNEMO_TEST_REAL_EMBED=1` and `POLYMNEMO_TEST_REAL_TOKENIZER=1`.

Layout: `src/polymnemo/` with `server.py` (tools) · `service.py` (logic) ·
`context.py` (composition root) · `auth/`, `store/`, `retriever/`, `embedding/`
(pluggable layers) · `chunking.py` · `config.py`.

## License

MIT — see [LICENSE](LICENSE).
