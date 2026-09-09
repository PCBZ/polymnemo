# Provision the media bucket and an S3-compatible credential for it, so a deploy
# comes up with media enabled and zero hand-set POLYMNEMO_BLOB_* vars.
#
# Cloudflare's provider only manages the bucket; it never shipped a first-class
# "R2 S3 access key" resource, and the ask to output S3 creds from a token was
# closed-as-not-planned (cloudflare/terraform-provider-cloudflare#2713, #2873).
# So we use the supported community pattern: mint an API token scoped to R2
# read+write, then derive the S3 pair — access_key_id = token id,
# secret_access_key = sha256(token value).
#
# CAVEAT: that derivation is undocumented, and some provider builds 403 on it
# (cloudflare/terraform-provider-cloudflare#6626). If `apply` — or the first
# upload — 403s, create an R2 API token in the dashboard and set
# POLYMNEMO_BLOB_ACCESS_KEY_ID / _SECRET_ACCESS_KEY by hand instead (see
# docs/deploy.md).

resource "cloudflare_r2_bucket" "media" {
  account_id = var.cf_account_id
  name       = var.bucket_name
  location   = var.location
}

# Resolve the R2 read/write permission-group ids by name rather than hardcoding
# their uuids. The `name` filter narrows server-side to the R2 groups; we then
# pick the exact two. Names resolve at apply against the live API — an upstream
# rename would surface as a null id here, not silently.
data "cloudflare_api_token_permission_groups_list" "r2" {
  name = "Workers R2 Storage"
}

locals {
  r2_read_pg = one([
    for g in data.cloudflare_api_token_permission_groups_list.r2.result :
    g.id if g.name == "Workers R2 Storage Bucket Item Read"
  ])
  r2_write_pg = one([
    for g in data.cloudflare_api_token_permission_groups_list.r2.result :
    g.id if g.name == "Workers R2 Storage Bucket Item Write"
  ])
}

resource "cloudflare_api_token" "r2" {
  name = var.token_name

  policies = [{
    effect = "allow"
    permission_groups = [
      { id = local.r2_read_pg },
      { id = local.r2_write_pg },
    ]
    # Scope the token to this account's R2. jsonencode produces the JSON-string
    # form the provider expects for `resources`.
    resources = jsonencode({
      "com.cloudflare.api.account.${var.cf_account_id}" = "*"
    })
  }]
}
