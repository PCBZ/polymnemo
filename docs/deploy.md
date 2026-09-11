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
   `POLYMNEMO_API_KEYS`).
3. **State storage** — `az login`, then `bash scripts/bootstrap-tfstate-azure.sh`.
   Creates the state storage account/container and publishes
   `TFSTATE_RESOURCE_GROUP` / `TFSTATE_STORAGE_ACCOUNT` / `TFSTATE_CONTAINER` as
   GitHub variables.
4. **Cut a release** — push a `v*` tag; the deploy runs on it (and
   registry-publish runs on the same tag), so **one tag = deployed state =
   registered version**:
   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```
   It builds + runs **that tag** (image tagged `polymnemo:v0.1.0`, built from the
   tag ref) and applies `neon` → schema → `r2` → `azure`, then prints the MCP
   endpoint. Rollback = deploy an older tag. For a manual/emergency deploy of a
   branch, use Actions → *deploy (azure)* → Run workflow instead (image tagged
   with the commit SHA).

The `azure` job **builds the image in the runner and pushes it to GHCR**
(`ghcr.io/<owner>/polymnemo:<tag>`, authenticated with the workflow's
`GITHUB_TOKEN` — no extra secret), then Terraform deploys that image; Azure only
runs it. (ACR Tasks are blocked on personal/student subscriptions, and the SP
can't create the AcrPull role assignment, so the image lives on GHCR instead of
ACR — public, so the app pulls it with no credentials.) Re-runnable (shared
remote state); `concurrency` blocks overlapping runs.

> **One-time:** make the GHCR `polymnemo` package **Public** (GitHub → your
> profile → Packages → `polymnemo` → Package settings → Change visibility →
> Public) so the app can pull it without credentials. Until it's public the app
> can't start, and the `azure` job **fails** on its post-deploy readiness check
> (it polls the app and errors if it never comes up) — so the first tagged deploy
> pushes the image and goes red, then you flip the package Public and re-run the
> `azure` job. Each run rolls a fresh revision, so the re-run picks up the change.

## Failover: deploy to GCP (backup, manual only)

`deploy gcp (backup)` (`.github/workflows/deploy-gcp.yml`) is a dormant failover
to Cloud Run — `workflow_dispatch` only, never auto-triggered. It applies **only**
the `gcp/` root and assumes the shared `neon` + `r2` (and `schema.sql`) already
exist from the Azure deploy. Cloud Run runs the **same public GHCR image** Azure
built — pulled directly, no Artifact Registry or Cloud Build — so it's one
Terraform apply. It reads the shared state from Azure Storage, so it needs
**both** GCP auth **and** the `ARM_*` secrets. It registers no MCP endpoint of its
own: Azure's (in `server.json`) is the one canonical endpoint both clouds share.

This is a **warm standby**, not automatic failover — GCP's Cloud Run URL differs
from Azure's and is never published. What's shared automatically is the *data*
(same Neon + R2), not the routing. So to actually fail over when Azure is down,
you repoint the endpoint yourself: set `server.json`'s `remotes[0].url` (or the
`mcp_endpoint` input) to the GCP URL and re-run *Publish to MCP Registry*. (A
shared custom domain / load balancer in front of both would make this automatic —
not set up here.)

One-time setup (in addition to the Azure secrets):

1. **Service account** — create a GCP SA with roles: `roles/run.admin`,
   `roles/iam.serviceAccountAdmin` (creates the runtime SA),
   `roles/iam.serviceAccountUser` (deploys the service *as* it), and
   `roles/serviceusage.serviceUsageAdmin` (enables the run API). Download a JSON
   key. (WIF / OIDC is the more secure, keyless alternative — a follow-up.)
2. **Secrets/variables**:
   ```bash
   gh secret set GCP_SA_KEY < path/to/key.json       # the SA JSON key
   gh variable set GCP_PROJECT_ID --body "<project>"
   ```
3. **Run it** — Actions → *deploy gcp (backup)* → Run workflow, giving an existing
   GHCR tag (e.g. `v1.0.0`, or `latest`). It deploys Cloud Run against the same
   shared Neon + R2 as Azure, then runs a post-deploy readiness check.

The rest of this doc describes the same variables for a **local** apply.

## Variables you actually set

**GCP path — 5 values (+ 1 env token):**

| Variable | Root | Notes |
| --- | --- | --- |
| `neon_api_key` 🔒 | neon | Neon console → API keys |
| `cf_account_id` | r2 | Cloudflare account id (media is always on) |
| `project_id` | gcp | GCP project id |
| `api_keys` 🔒 | gcp | `key1:alice,key2:bob` → `POLYMNEMO_API_KEYS` |
| `image` | gcp | Public GHCR ref Cloud Run pulls, e.g. `ghcr.io/<owner>/polymnemo:v1.0.0` |

Plus `export CLOUDFLARE_API_TOKEN=…` before applying the `r2` root (a token with
R2 edit + API Tokens edit). **Azure path:** swap `project_id` for
`azure_subscription_id`, and set `image` to the GHCR ref you pushed
(`ghcr.io/<owner>/polymnemo:<tag>`, made Public); the rest match.

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
