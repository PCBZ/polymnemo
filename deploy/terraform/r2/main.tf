# The single, SHARED R2 bucket for media blobs (+ its S3 credentials). Both the
# gcp/ and azure/ roots read these via terraform_remote_state, so a file uploaded
# from one cloud is downloadable from the other — the same "one shared backend"
# model as the neon/ root. Media is OPTIONAL: apply this root only if you want
# the media tools on, then set media_enabled=true in the compute root(s).
#
# Usage:
#   1. cp terraform.tfvars.example terraform.tfvars   # cf_account_id
#   2. export CLOUDFLARE_API_TOKEN=<token: R2 edit + API Tokens edit>
#   3. terraform init && terraform apply
#
# Then apply the gcp/ and/or azure/ roots with media_enabled=true.

module "r2" {
  source        = "../modules/r2"
  cf_account_id = var.cf_account_id
  bucket_name   = var.bucket_name
  location      = var.location
  token_name    = var.token_name
}
