# GCP compute: Cloud Run, reading the SHARED Neon connection string from the
# neon root's state. Apply the neon root (and its schema.sql) first.
#
# Usage:
#   1. (once) apply deploy/terraform/neon + its schema.sql
#   2. cp terraform.tfvars.example terraform.tfvars   # project_id, region, api_keys
#   3. terraform init && terraform apply               # bootstrap: APIs + registry
#   4. REPO="$(terraform output -raw image_repo)"
#      gcloud builds submit ../../../ --tag "$REPO/polymnemo:v1"
#   5. terraform apply -var "image=$REPO/polymnemo:v1"
#   6. terraform output -raw mcp_endpoint

# Reads the shared Neon root's state over a LOCAL relative path — this requires
# all three roots in one checkout, applied on one machine, neon applied first.
# For CI or a second operator, a shared remote backend is REQUIRED (see neon/versions.tf).
data "terraform_remote_state" "neon" {
  backend = "local"
  config = {
    path = "../neon/terraform.tfstate"
  }
}

# The SHARED media bucket + S3 creds, from the r2/ root's state — the same
# read-only pattern as the neon data source above, so GCP and Azure use the
# *same* R2. Only read when media_enabled; a DB-only deploy has no r2/ state.
data "terraform_remote_state" "r2" {
  count   = var.media_enabled ? 1 : 0
  backend = "local"
  config = {
    path = "../r2/terraform.tfstate"
  }
}

module "cloud_run" {
  source       = "../modules/cloud-run"
  project_id   = var.project_id
  region       = var.region
  service_name = var.service_name
  image        = var.image
  database_url = data.terraform_remote_state.neon.outputs.connection_uri_pooler
  api_keys     = var.api_keys

  # Media/blob wiring — inert (backend "none") unless media_enabled.
  blob_backend           = var.media_enabled ? "s3" : "none"
  blob_bucket            = try(data.terraform_remote_state.r2[0].outputs.bucket, "")
  blob_endpoint_url      = try(data.terraform_remote_state.r2[0].outputs.endpoint_url, "")
  blob_access_key_id     = try(data.terraform_remote_state.r2[0].outputs.access_key_id, "")
  blob_secret_access_key = try(data.terraform_remote_state.r2[0].outputs.secret_access_key, "")
}

# Auto-fill the deployed /mcp endpoint into a GitHub Actions variable, so the
# registry-publish workflow can put it into server.json on release — no manual
# copy of the URL. Only once the service exists (image set).
resource "github_actions_variable" "mcp_endpoint" {
  count         = var.image == "" ? 0 : 1
  repository    = var.github_repository
  variable_name = "MCP_ENDPOINT"
  value         = module.cloud_run.mcp_endpoint
}
