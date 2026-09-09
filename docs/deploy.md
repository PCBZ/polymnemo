# Deploying polymnemo

polymnemo deploys with Terraform across **two roots**: `deploy/terraform/neon`
(the shared Postgres) applied once, then **one** compute root —
`deploy/terraform/gcp` (Cloud Run) or `deploy/terraform/azure` (Container Apps),
which read Neon's connection string from its state. Both compute targets can run
against the same Neon so memories are shared.

Most configuration is either baked into the image or wired automatically; you
set only a handful of variables.

## Variables you actually set

**GCP path — 4 values:**

| Variable | Root | Notes |
| --- | --- | --- |
| `neon_api_key` 🔒 | neon | Neon console → API keys |
| `project_id` | gcp | GCP project id |
| `api_keys` 🔒 | gcp | `key1:alice,key2:bob` → `POLYMNEMO_API_KEYS` |
| `image` | gcp | Set on the **second** apply; empty on the bootstrap apply |

**Azure path — 5 values:** swap `project_id` for `azure_subscription_id` +
`acr_name` (globally unique); the rest match.

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

## Media / large files (Cloudflare R2) — optional, fully automated

Media tools are **off** unless you provision R2. To turn them on with zero
hand-set `POLYMNEMO_BLOB_*` vars, set **one** variable and export a Cloudflare
token:

```hcl
# terraform.tfvars (gcp or azure)
cf_account_id = "your-cloudflare-account-id"
```
```bash
export CLOUDFLARE_API_TOKEN=<token: R2 edit + API Tokens edit>
terraform apply
```

Terraform then (`modules/r2`) creates the bucket, mints an R2-scoped API token,
derives the S3 credentials, and injects `POLYMNEMO_BLOB_BACKEND=s3` plus the
bucket / endpoint / key / secret into the service. Leave `cf_account_id` unset
for a database-only deploy.

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
Key ID + Secret Access Key directly, then set them by hand on the service —
`POLYMNEMO_BLOB_ACCESS_KEY_ID` and `POLYMNEMO_BLOB_SECRET_ACCESS_KEY` — and drop
`cf_account_id` so Terraform doesn't try to derive them. The bucket can still be
Terraform-managed.

### Not yet automated

- **CORS** (for browser-side direct uploads) and **object lifecycle** need the
  AWS provider — the Cloudflare provider only manages the bucket. Deferred.
- **Sweeping abandoned unconfirmed uploads** —
  [#53](https://github.com/PCBZ/polymnemo/issues/53).
