# Deploying polymnemo

polymnemo deploys with Terraform across **two shared roots** applied once each —
`deploy/terraform/neon` (the shared Postgres) and `deploy/terraform/r2` (the
shared media bucket) — then **one** compute root: `deploy/terraform/gcp`
(Cloud Run) or `deploy/terraform/azure` (Container Apps), which read both shared
roots' state. Both compute targets run against the same Neon *and* the same R2,
so memories and media are shared across clouds.

Most configuration is either baked into the image or wired automatically; you
set only a handful of variables.

## Variables you actually set

**GCP path — 5 values (+ 1 env token):**

| Variable | Root | Notes |
| --- | --- | --- |
| `neon_api_key` 🔒 | neon | Neon console → API keys |
| `cf_account_id` | r2 | Cloudflare account id (media is on by default) |
| `project_id` | gcp | GCP project id |
| `api_keys` 🔒 | gcp | `key1:alice,key2:bob` → `POLYMNEMO_API_KEYS` |
| `image` | gcp | Set on the **second** apply; empty on the bootstrap apply |

Plus `export CLOUDFLARE_API_TOKEN=…` before applying the `r2` root (a token with
R2 edit + API Tokens edit). **Azure path — 6 values:** swap `project_id` for
`azure_subscription_id` + `acr_name` (globally unique); the rest match.

Don't want media? Set `media_enabled = false` on the compute root and skip the
`r2` root + Cloudflare entirely — that drops you back to 4 values (GCP) / 5
(Azure).

Everything else has a default: `region`/`location`, `service_name`, instance
sizing, `github_owner`/`github_repository`.

## What you do NOT set (wired for you)

- **`POLYMNEMO_DATABASE_URL`** — the compute root reads Neon's pooled connection
  string from its state (`terraform_remote_state`) and injects it.
- **`POLYMNEMO_HOST` / `REQUIRE_DATABASE` / `EMBED_MODEL`** — baked into the
  image (Cloud Run also injects `$PORT`).
- **`MCP_ENDPOINT`** (for registry-publish) — Terraform writes the deployed
  `/mcp` URL into the repo's GitHub Actions variable after apply. Export
  `GITHUB_TOKEN` before `apply` to enable it; skip it otherwise.

## Media / large files (Cloudflare R2) — on by default, fully automated

Media tools (upload / download of files, images, video) are **on by default**.
They mirror the Neon setup: a dedicated **`deploy/terraform/r2` root** owns the
**one** bucket + S3 credentials, and each compute root *reads* it
(`terraform_remote_state`) — so GCP and Azure share the **same** R2, exactly like
they share the same Neon. (If they didn't, a file uploaded via one cloud would
404 when downloaded via the other, since the media row lives in the shared Neon
and points at one `object_key`.)

Because it's on by default, the `r2` root is a standard deploy step (like
`neon`), applied before the compute root:

```bash
cd deploy/terraform/r2
cp terraform.tfvars.example terraform.tfvars      # set cf_account_id
export CLOUDFLARE_API_TOKEN=<token: R2 edit + API Tokens edit>
terraform init && terraform apply
```

The `r2` root (`modules/r2`) creates the bucket, mints an R2-scoped API token,
and derives the S3 credentials; the compute root then reads them and injects
`POLYMNEMO_BLOB_BACKEND=s3` plus the bucket / endpoint / key / secret into the
service.

**Database-only deploy:** set `media_enabled = false` on the compute root and
skip the `r2` root entirely — no Cloudflare dependency, media tools off.

### If R2 uploads 403 (escape hatch)

The S3 credentials are **derived** from the API token
(`access_key_id = token id`, `secret_access_key = sha256(token value)`) — the
only way to get them in Terraform, since Cloudflare never shipped a first-class
resource for this
([#2713](https://github.com/cloudflare/terraform-provider-cloudflare/issues/2713),
[#2873](https://github.com/cloudflare/terraform-provider-cloudflare/issues/2873)).
Some provider builds have 403'd on the derived pair
([#6626](https://github.com/cloudflare/terraform-provider-cloudflare/issues/6626)).

If `apply` or the first upload 403s: create an **R2 API token** in the
Cloudflare dashboard (R2 → *Manage R2 API Tokens*), which hands you an Access
Key ID + Secret Access Key directly. Then leave `media_enabled = false` (so the
compute root doesn't read the derived creds) and set the four `POLYMNEMO_BLOB_*`
env vars by hand on the service — `_BACKEND=s3`, `_BUCKET`, `_ENDPOINT_URL`,
`_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY`. The bucket can still be Terraform-managed
by the `r2/` root.

### Not yet automated

- **CORS** (for browser-side direct uploads) and **object lifecycle** need the
  AWS provider — the Cloudflare provider only manages the bucket. Deferred.
- **Sweeping abandoned unconfirmed uploads** —
  [#53](https://github.com/PCBZ/polymnemo/issues/53).
