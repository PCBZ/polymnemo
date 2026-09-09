# polymnemo

[![CI](https://github.com/PCBZ/polymnemo/actions/workflows/ci.yml/badge.svg)](https://github.com/PCBZ/polymnemo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

**A shared long-term memory across any LLM, over [MCP](https://modelcontextprotocol.io).**

Point Claude Desktop, an MCP-capable IDE, or any MCP client at one polymnemo
endpoint and they share the same memories — stored in your own Postgres. Store a
fact with one assistant, recall it from another; save whole sessions and reload
them; even attach files, images, or video. Embeddings run locally (no embedding
API key), and the server makes no generative-LLM calls.

> **Status:** active development. Semantic memory + pgvector store, session
> save/reload, and multimedia memories all work; deployable to Azure Container
> Apps (or Cloud Run) via Terraform.
> [Wiki](https://github.com/PCBZ/polymnemo/wiki) · [Issues](https://github.com/PCBZ/polymnemo/issues)

```mermaid
flowchart LR
    Clients["MCP clients<br/>(Claude Desktop, IDEs, …)"] -->|"/mcp · Bearer key"| P["polymnemo<br/>(MCP server)"]
    P --> DB[("Postgres + pgvector<br/>text + pointers")]
    P -. "large files<br/>(presigned URLs)" .-> OS[("Object storage<br/>S3 / R2")]
```

## Quickstart

Requires **Python 3.11+**.

### 1. Install

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[postgres]"         # add ,blob for media memories: ".[postgres,blob]"
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
| `create_upload` | `filename`, `content_type`, `description`, `namespace?` | `{memory_id, object_key, upload_url, upload_headers, …}` |
| `confirm_upload` | `id` | `{memory_id, confirmed, size_bytes, content_type}` |
| `get_download_url` | `id` | `{memory_id, url, content_type}` |

Large `content` is split into chunks on write (one vector each), so `remember`
may return several ids. `recall` returns the nearest chunks by similarity, paged
with `next_cursor`. Sessions store a full transcript that `load_session`
reconstructs verbatim; they default to a private namespace (`sessions`).

**Media memories** (files, images, video) keep the bytes in object storage, not
the database: `create_upload` returns a presigned URL you PUT the bytes to,
`confirm_upload` records the real size/checksum and reveals it, and
`get_download_url` mints a short-lived download link. The bytes never cross the
MCP channel — only a searchable `description` is embedded — and media defaults to
a private namespace (`media`). Requires the `blob` extra + object storage (see
Configuration).

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
| `POLYMNEMO_RATELIMIT_ENABLED` / `_PER_MIN` | `false` / `600` | Optional global rate limit (ops per minute). |
| `POLYMNEMO_BLOB_BACKEND` (+ `_BUCKET` / `_ENDPOINT_URL` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY`) | `none` | Object storage for media memories; `s3` = Cloudflare R2 / S3-compatible. |

## Development

```bash
pip install -e ".[dev]"
pytest                               # fast, offline (stub embedder, in-memory store)
ruff check . && ruff format --check .   # lint + format (enforced in CI)
```

Postgres tests run when `TEST_DATABASE_URL` points at a pgvector Postgres. CI
(`.github/workflows/ci.yml`) runs lint + the suite with coverage and posts a
pass/fail/coverage table to each run's summary.

## Deploy

polymnemo is stateless (all state in Neon + object storage), so it runs on
**Azure Container Apps** (primary) or **Google Cloud Run** with scale-to-zero.
Everything is Terraform in [`deploy/terraform/`](deploy/terraform): shared
[`neon/`](deploy/terraform/neon) (Postgres) and [`r2/`](deploy/terraform/r2)
(media bucket) roots own the durable state, and a compute root deploys a service
that reads both — so memories *and* media are shared across clouds.

The Azure path deploys from CI in one click: set the GitHub secrets
(`scripts/setup-github-secrets.sh`), bootstrap the state backend
(`scripts/bootstrap-tfstate-azure.sh`), then run the **deploy (azure)** workflow
(`neon → schema → r2 → build → app`). GCP is a manual failover. Full walkthrough
in [`docs/deploy.md`](docs/deploy.md).

## License

MIT — see [LICENSE](LICENSE).
