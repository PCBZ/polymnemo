# polymnemo

**A shared long-term memory across any LLM, over [MCP](https://modelcontextprotocol.io).**

Point Claude Desktop, an MCP-capable IDE, or any MCP client at one polymnemo
endpoint and they share the same memories — stored in your own Postgres. Store a
fact with one assistant, recall it from another. Embeddings run locally (no
embedding API key), and the server makes no generative-LLM calls.

> **Status:** early development; the MVP (semantic memory + pgvector store) works.
> [Wiki](https://github.com/PCBZ/polymnemo/wiki) · [Issues](https://github.com/PCBZ/polymnemo/issues)

```mermaid
flowchart LR
    Clients["MCP clients<br/>(Claude Desktop, IDEs, …)"] -->|"/mcp · Bearer key"| P["polymnemo<br/>(MCP server)"] --> DB[("Postgres + pgvector")]
```

## Quickstart

Requires **Python 3.11+**.

### 1. Install

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[postgres]"
```

### 2. Provision Postgres (pgvector)

The durable store is Postgres + [pgvector](https://github.com/pgvector/pgvector);
the easiest hosted option is [Neon](https://neon.tech) (use the **pooled**
connection string). Apply the schema once:

```bash
psql "<your-connection-string>" -f scripts/schema.sql
```

### 3. Configure

Copy `.env.example` to `.env` and set the database URL and at least one API key:

```bash
POLYMNEMO_DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
POLYMNEMO_API_KEYS=sk-alice-secret:alice,sk-bob-secret:bob   # "key:user_id" pairs
```

Each key maps a bearer token to a `user_id`; writes are scoped to that user.

### 4. Run

```bash
polymnemo                            # Streamable HTTP at http://127.0.0.1:8000/mcp
```

Or with Docker:

```bash
docker build -t polymnemo .
docker run -e POLYMNEMO_DATABASE_URL="..." -e POLYMNEMO_API_KEYS="sk-alice-secret:alice" \
           -e PORT=8080 -p 8080:8080 polymnemo
```

### 5. Connect an MCP client

Any client that supports remote (HTTP) MCP servers with custom headers needs two
things:

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

Or verify with the inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP · URL: http://127.0.0.1:8000/mcp
# Header:    Authorization: Bearer sk-alice-secret  → call ping / remember / recall
```

## Tools

Every call is authenticated by the bearer key (which resolves to a `user_id`).
Writes are owner-scoped; reads see your own memories plus anything in a *shared*
namespace (defaults to `shared`).

| Tool | Arguments | Returns |
|------|-----------|---------|
| `ping` | — | `{ok, server, version, layers}` |
| `remember` | `content`, `namespace?`, `tags?`, `source?` | `{ids, chunks, namespace}` |
| `recall` | `query`, `namespace?`, `limit=8`, `cursor?` | `{items, total, has_more, next_cursor}` |
| `list_memories` | `namespace?`, `limit=20`, `cursor?` | `{items, total, has_more, next_cursor}` |
| `get_memory` | `id` | the memory |
| `update` | `id`, `content` | the updated memory |
| `forget` | `id` | `{id, deleted}` |
| `save_session` | `session_id`, `content`, `namespace?` | `{session_id, chunks, chars, namespace}` |
| `load_session` | `session_id`, `page=0`, `page_size=8000` | `{session_id, content, page, page_size, total_chars, has_more}` |

Large `content` is split into chunks on write (one vector each), so `remember`
may return several ids. `recall` returns the nearest chunks by similarity, paged
with `next_cursor`. Sessions store a full transcript that `load_session`
reconstructs verbatim; they default to a private namespace (`sessions`).

**Resource** — `memory://{namespace}` exposes a namespace's memories (same shape
as `list_memories`) so a client can auto-inject the collection.

## Configuration

`POLYMNEMO_*` environment variables (or `.env`) — full list in
[.env.example](.env.example). The essentials:

| Variable | Default | Purpose |
|----------|---------|---------|
| `POLYMNEMO_DATABASE_URL` | *(unset)* | Postgres+pgvector DSN. Required in production; unset → in-memory (dev/tests). |
| `POLYMNEMO_API_KEYS` | *(empty)* | `"key1:alice,key2:bob"` — required for bearer auth. |
| `POLYMNEMO_SHARED_NAMESPACES` | `shared` | Namespaces readable by every user. |
| `POLYMNEMO_HOST` / `POLYMNEMO_PORT` / `POLYMNEMO_MCP_PATH` | `127.0.0.1` / `8000` / `/mcp` | Transport. |

## Development

```bash
pip install -e ".[dev]"
pytest                               # fast, offline (stub embedder, in-memory store)
```

Postgres tests run when `TEST_DATABASE_URL` points at a pgvector Postgres.

## License

MIT — see [LICENSE](LICENSE).
