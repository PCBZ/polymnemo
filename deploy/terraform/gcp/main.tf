# GCP compute: Cloud Run, running the SAME public GHCR image as Azure and
# reading the SAME shared Neon + R2 state — so it's a parallel instance over the
# same memories + media. A dormant BACKUP to the primary Azure deploy.
#
# Usually applied by the backup workflow (.github/workflows/deploy-gcp.yml,
# manual only). One apply does everything — Cloud Run pulls the public image
# directly (no Artifact Registry / Cloud Build). Manual flow, after neon/ + r2/
# are applied (state lives in Azure Storage — pass -backend-config at init):
#   1. cp terraform.tfvars.example terraform.tfvars   # project_id, image, api_keys, tfstate_*
#   2. terraform init -backend-config=...key=gcp.tfstate && terraform apply
#   3. terraform output -raw mcp_endpoint
#
# The shared neon/ and r2/ roots keep their state in the Azure Storage backend
# (see neon/versions.tf), so this root reads them from there too — meaning a GCP
# deploy needs Azure credentials (ARM_* env) just to READ the shared state. That
# cross-cloud coupling is the deliberate cost of ONE shared Neon + R2 across both
# clouds. Apply neon/ and r2/ before this root.
#
# It does NOT register its own MCP endpoint: Azure is primary, and the registered
# endpoint (in server.json) is the single canonical one both clouds share.
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
