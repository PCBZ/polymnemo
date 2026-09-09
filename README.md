# polymnemo

[![CI](https://github.com/PCBZ/polymnemo/actions/workflows/ci.yml/badge.svg)](https://github.com/PCBZ/polymnemo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![Python](https://img.shields.io/badge/Python_3.11%2B-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-FastMCP-000000?logo=modelcontextprotocol&logoColor=white)
![Postgres](https://img.shields.io/badge/Postgres_%2B_pgvector-4169E1?logo=postgresql&logoColor=white)
![Neon](https://img.shields.io/badge/Neon-008B47?logo=neon&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?logo=sqlalchemy&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white)
![Cloudflare R2](https://img.shields.io/badge/Cloudflare_R2-F38020?logo=cloudflare&logoColor=white)
![Azure](https://img.shields.io/badge/Azure_Container_Apps-0078D4)
![Cloud Run](https://img.shields.io/badge/Cloud_Run-4285F4?logo=googlecloud&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-844FBA?logo=terraform&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-261230?logo=ruff&logoColor=white)

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

## Features

- 🔗 **Cross-LLM shared** — point any MCP client at one endpoint; they share the same memory.
- 🧠 **Semantic recall** — vector search over Postgres + pgvector, not keyword matching.
- 💬 **Sessions** — save a full transcript and reload it verbatim, or recall across it.
- 🖼️ **Multimedia** — attach files, images, or video; bytes go to object storage, only a searchable description is embedded.
- 🔒 **Local & private** — embeddings run locally (ONNX): no embedding API key, and no generative-LLM calls, ever.
- 👥 **Namespaces** — "born-shared" collections readable by everyone, vs. private-to-owner; writes are always owner-scoped.
- 🧩 **Pluggable layers** — store, embedder, auth, retriever, blob store, and rate limiter are all swappable `Protocol`s.
- ☁️ **Multi-cloud deploy** — one Terraform stack to Azure Container Apps or Cloud Run, scale-to-zero.
- 🚦 **Rate limiting** — optional global token bucket.

## How it works

```mermaid
flowchart LR
    Clients["MCP clients<br/>(Claude Desktop, IDEs, …)"] -->|"/mcp · Bearer key"| P["polymnemo<br/>(MCP server)"]
    P --> DB[("Postgres + pgvector<br/>text + pointers")]
    P -. "large files<br/>(presigned URLs)" .-> OS[("Object storage<br/>S3 / R2")]
```

A request carries a bearer key (which resolves to a `user_id`); the tool passes
the rate-limit gate, then delegates to a `MemoryService` that chunks + embeds
text and stores the vectors in pgvector — large files go to object storage via
presigned URLs, with only a searchable description embedded.

Every layer is a `typing.Protocol`, wired together by a composition root
([`context.py`](src/polymnemo/context.py)), so you can swap an implementation
without touching the tools:

| Layer | Default | Swap for |
|-------|---------|----------|
| **Store** | `PostgresStore` (pgvector) | `InMemoryStore` (dev/tests) |
| **Embedder** | `fastembed` (local ONNX) | `StubEmbedder` (offline) |
| **Auth** | per-user bearer keys | static single-user (dev) |
| **Retriever** | `VectorRetriever` | your own ranker |
| **BlobStore** | S3 / R2 | off |
| **RateLimiter** | global token bucket | off |

The `ping` tool returns the active layers, so you can see how a running server is
wired.

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

## Concepts

- **Users & keys** — each bearer key maps to a `user_id`; writes are owner-scoped
  (you can only edit or delete your own memories).
- **Namespaces** — memories live in namespaces. A *shared* namespace (default
  `shared`) is readable by everyone ("born shared"); everything else is private
  to its owner. Sessions and media default to private namespaces.
- **Chunking** — long content is split into chunks on write (one vector each), so
  `remember` may return several ids and `recall` returns the closest chunks.

## Tools

polymnemo exposes MCP tools for storing, searching, and managing memories:

- **Memory** — `remember`, `recall`, `list_memories`, `get_memory`, `update`, `forget`
- **Sessions** — `save_session`, `load_session`
- **Media** — `create_upload`, `confirm_upload`, `get_download_url`

Plus a `ping` health check and a `memory://{namespace}` resource for
auto-injecting a collection. Media bytes go to object storage via presigned URLs
— never through the MCP channel — with only a searchable description embedded
(needs the `blob` extra).

Full arguments and return shapes live in the dedicated **MCP tools reference**
*(coming soon)*. See [Concepts](#concepts) for how keys, namespaces, and chunking
work.

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
