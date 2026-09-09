# GCP compute: Cloud Run — the BACKUP deploy path (primary is Azure). Reads the
# SHARED Neon + R2 state from the Azure Storage backend, so it needs ARM_* creds
# just to read it. Usually run by the manual .github/workflows/deploy-gcp.yml.
# Assumes neon/ + r2/ (and schema.sql) are already provisioned by the Azure deploy.
#
# Manual flow (state is in Azure Storage — pass -backend-config at init):
#   1. terraform init \
#        -backend-config=resource_group_name=<rg> \
#        -backend-config=storage_account_name=<sa> \
#        -backend-config=container_name=tfstate \
#        -backend-config=key=gcp.tfstate
#   2. terraform apply                                 # bootstrap: APIs + registry
#   3. REPO="$(terraform output -raw image_repo)"
#      gcloud builds submit ../../../ --tag "$REPO/polymnemo:$(git rev-parse HEAD)"
#   4. terraform apply -var "image=$REPO/polymnemo:$(git rev-parse HEAD)"
#   5. terraform output -raw mcp_endpoint

# The shared neon/ and r2/ roots keep their state in the Azure Storage backend
# (see neon/versions.tf), so this root reads them from there too — meaning a GCP
# deploy needs Azure credentials (ARM_* env) just to READ the shared state. That
# cross-cloud coupling is the deliberate cost of ONE shared Neon + R2 across both
# clouds: the shared state has to live somewhere, and that's Azure Storage. (This
# root keeps its OWN state local — it's a manual, secondary path with no CI.)
# Apply neon/ and r2/ before this root.
data "terraform_remote_state" "neon" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "neon.tfstate"
  }
}

data "terraform_remote_state" "r2" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "r2.tfstate"
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

  # Media/blob wiring — always on, from the shared r2/ root.
  blob_backend           = "s3"
  blob_bucket            = data.terraform_remote_state.r2.outputs.bucket
  blob_endpoint_url      = data.terraform_remote_state.r2.outputs.endpoint_url
  blob_access_key_id     = data.terraform_remote_state.r2.outputs.access_key_id
  blob_secret_access_key = data.terraform_remote_state.r2.outputs.secret_access_key
}

# Auto-fill the deployed /mcp endpoint into a GitHub Actions variable, so the
# registry-publish workflow can put it into server.json on release — no manual
# copy of the URL. Only once the service exists (image set), and only when this
# deploy should own the registered endpoint (the backup GCP path opts out).
resource "github_actions_variable" "mcp_endpoint" {
  count         = var.image != "" && var.publish_mcp_endpoint ? 1 : 0
  repository    = var.github_repository
  variable_name = "MCP_ENDPOINT"
  value         = module.cloud_run.mcp_endpoint
}
