# Listing polymnemo in the MCP Registry

polymnemo is a **remote (hosted) MCP server**, not a local package — so it's
listed as a `remotes` entry pointing at a public instance you run. Discovery is
optional: skip all of this if you only ever use your own deployment.

## Steps

The endpoint URL flows from Terraform → a GitHub Actions variable → the publish
workflow. You never hand-copy the URL.

1. **Deploy a public instance.** Apply the `deploy/terraform/gcp` root (Cloud Run;
   `--allow-unauthenticated` exposes the endpoint, not the data — polymnemo still
   enforces bearer auth). Export a GitHub token first so Terraform can set the CI
   variable:

   ```bash
   export GITHUB_TOKEN=<a token with repo + actions:write on PCBZ/polymnemo>
   terraform apply -var "image=…"   # also sets the MCP_ENDPOINT Actions variable
   ```

   That `github_actions_variable` resource writes `<service-url>/mcp` into the
   repo's **`MCP_ENDPOINT`** variable automatically.

2. **Publish — cut a release tag.** No manual edits:

   ```bash
   git tag v0.0.1 && git push origin v0.0.1
   ```

   The [`registry-publish.yml`](../.github/workflows/registry-publish.yml) workflow
   (also runnable from **Actions → Run workflow**):
   - **syncs `server.json`** — URL from `MCP_ENDPOINT`, version from the tag —
     and **commits that change back to `main`** (so the committed file matches
     what's published);
   - authenticates via **GitHub OIDC** (no browser, no secret — the token proves
     this repo owns `io.github.PCBZ/*`) and runs `mcp-publisher publish`.

   It no-ops until `MCP_ENDPOINT` is set (i.e. until step 1 has run). If `main` is
   branch-protected, allow the `github-actions` bot to push, or the commit step
   will fail.

3. **Verify** in the [official registry](https://registry.modelcontextprotocol.io);
   optionally submit to Glama / mcpservers.org.

To publish from your laptop instead: `mcp-publisher login github` (browser) →
edit `server.json`'s url + version → `mcp-publisher publish`.

## Before you make it truly public

A public instance means anyone can *reach* the URL. Two things matter:

- **Access is key-gated.** With the current `POLYMNEMO_API_KEYS` (a static
  env-var map), only keys you issue by hand work — there is no self-service
  sign-up yet. So "public" = discoverable + reachable, but you hand out keys.
  Real self-service needs user/key management (a users/api_keys table) — a
  separate feature.
- **Abuse protection.** Enable rate limiting (`POLYMNEMO_RATELIMIT_ENABLED=true`)
  before exposing it; media uploads default to a private namespace already.
