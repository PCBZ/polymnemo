# Deploying polymnemo

polymnemo deploys with Terraform across **two shared roots** applied once each —
`deploy/terraform/neon` (the shared Postgres) and `deploy/terraform/r2` (the
shared media bucket) — then **one** compute root: `deploy/terraform/gcp`
(Cloud Run) or `deploy/terraform/azure` (Container Apps), which read both shared
roots' state. Both compute targets run against the same Neon *and* the same R2,
so memories and media are shared across clouds.

Most configuration is either baked into the image or wired automatically; you
set only a handful of variables.

Terraform state lives in an **Azure Storage** backend (so CI and multiple
operators share it); the storage account/container are passed at
`terraform init -backend-config` time, not hardcoded.

## Deploy from CI (GitHub Actions — Azure)

The `deploy (azure)` workflow (`.github/workflows/deploy.yml`) runs the whole
chain from GitHub Secrets/Variables — nothing lands in `.env`/`tfvars`. One-time
setup:

1. **Service principal** — `az ad sp create-for-rbac --role Contributor --scopes
   /subscriptions/<sub>` → its `appId`/`password`/`tenant` + the subscription id
   become the `ARM_*` secrets.
2. **Push secrets** — fill `scripts/github-secrets.env` (copied from the
   `.template`) and run `bash scripts/setup-github-secrets.sh`. Sets the 8
   secrets (`ARM_*`, `NEON_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CF_ACCOUNT_ID`,
   `POLYMNEMO_API_KEYS`) + the `ACR_NAME` variable.
3. **State storage** — `az login`, then `bash scripts/bootstrap-tfstate-azure.sh`.
   Creates the state storage account/container and publishes
   `TFSTATE_RESOURCE_GROUP` / `TFSTATE_STORAGE_ACCOUNT` / `TFSTATE_CONTAINER` as
   GitHub variables.
4. **Run it** — Actions tab → *deploy (azure)* → Run workflow. It applies
   `neon` → schema → `r2` → `azure`. The `azure` apply builds the image **inside
   ACR** (Terraform's `azurerm_container_registry_task`, no `az acr build` / azure
   login) and deploys it in one step, then prints the MCP endpoint. Re-runnable
   (shared remote state); `concurrency` blocks overlapping runs; the run forces a
   fresh image build each time with `-replace`.

The image build clones the public repo, so the build's `context_access_token` is
the workflow's short-lived `GITHUB_TOKEN` — no extra secret. (A private repo
would need a real PAT here instead.)

## Failover: deploy to GCP (backup, manual only)

`deploy gcp (backup)` (`.github/workflows/deploy-gcp.yml`) is a dormant failover
to Cloud Run — `workflow_dispatch` only, never auto-triggered. It applies **only**
the `gcp/` root and assumes the shared `neon` + `r2` (and `schema.sql`) already
exist from the Azure deploy; it reads that shared state from Azure Storage, so it
needs **both** GCP auth **and** the `ARM_*` secrets.

One-time setup (in addition to the Azure secrets):

1. **Service account** — create a GCP SA with roles: `roles/run.admin`,
   `roles/cloudbuild.builds.editor`, `roles/artifactregistry.admin`,
   `roles/iam.serviceAccountUser`, `roles/serviceusage.serviceUsageAdmin`.
   Download a JSON key.
2. **Secrets/variables**:
   ```bash
   gh secret set GCP_SA_KEY < path/to/key.json      # the SA JSON key
   gh variable set GCP_PROJECT_ID --body "<project>"
   ```
   (WIF / OIDC is the more secure alternative to a long-lived key — a follow-up.)
3. **Run it** — Actions → *deploy gcp (backup)* → Run workflow. It bootstraps the
   Artifact Registry, builds the image with `gcloud builds submit` (tagged with
   the commit SHA), and deploys Cloud Run against the same shared Neon + R2 as
   Azure. It sets `publish_mcp_endpoint = false`, so it does **not** overwrite the
   registered (Azure) `MCP_ENDPOINT`.

The rest of this doc describes the same variables for a **local** apply.

## Variables you actually set

**GCP path — 5 values (+ 1 env token):**

| Variable | Root | Notes |
| --- | --- | --- |
| `neon_api_key` 🔒 | neon | Neon console → API keys |
| `cf_account_id` | r2 | Cloudflare account id (media is always on) |
| `project_id` | gcp | GCP project id |
| `api_keys` 🔒 | gcp | `key1:alice,key2:bob` → `POLYMNEMO_API_KEYS` |
| `image` | gcp | Set on the **second** apply; empty on the bootstrap apply |

Plus `export CLOUDFLARE_API_TOKEN=…` before applying the `r2` root (a token with
R2 edit + API Tokens edit). **Azure path — 6 values:** swap `project_id` for
`azure_subscription_id` + `acr_name` (globally unique); the rest match.

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

## Media / large files (Cloudflare R2) — always on, fully automated

Media tools (upload / download of files, images, video) are **always on** — a
core capability, not a toggle. They mirror the Neon setup: a dedicated
**`deploy/terraform/r2` root** owns the **one** bucket + S3 credentials, and each
compute root *reads* it (`terraform_remote_state`) — so GCP and Azure share the
**same** R2, exactly like they share the same Neon. (If they didn't, a file
uploaded via one cloud would 404 when downloaded via the other, since the media
row lives in the shared Neon and points at one `object_key`.)

The `r2` root is a standard deploy step (like `neon`), applied before the compute
root:

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
Cloudflare dashboard (R2 → *Manage R2 API Tokens*), which hands you an Access Key
ID + Secret Access Key directly, then set both on the **`r2` root** —
`access_key_id` and `secret_access_key` in its `terraform.tfvars`. Terraform then
skips the derivation and uses your pre-made pair; the bucket and everything
downstream stay Terraform-managed and media stays on.

### Not yet automated

- **CORS** (for browser-side direct uploads) and **object lifecycle** need the
  AWS provider — the Cloudflare provider only manages the bucket. Deferred.
- **Sweeping abandoned unconfirmed uploads** —
  [#53](https://github.com/PCBZ/polymnemo/issues/53).
