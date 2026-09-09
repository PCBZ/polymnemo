# The single, SHARED R2 bucket for media blobs (+ its S3 credentials). Both the
# gcp/ and azure/ roots read these via terraform_remote_state, so a file uploaded
# from one cloud is downloadable from the other — the same "one shared backend"
# model as the neon/ root. Media is always on, so this is a required root (apply
# it before the compute root, like neon/).
#
# Usage:
#   1. cp terraform.tfvars.example terraform.tfvars   # cf_account_id
#   2. export CLOUDFLARE_API_TOKEN=<token: R2 edit + API Tokens edit>
#   3. terraform init && terraform apply
#
# Then apply the gcp/ and/or azure/ roots (they read this root's state).

module "r2" {
  source        = "../modules/r2"
  cf_account_id = var.cf_account_id
  bucket_name   = var.bucket_name
  location      = var.location
  token_name    = var.token_name

  # Escape hatch: pass pre-made creds to skip the derivation (see #6626).
  access_key_id     = var.access_key_id
  secret_access_key = var.secret_access_key
}
