# Azure compute: Container Apps, reading the SAME shared Neon connection string
# from the neon root's state — so memories are shared with the GCP deployment.
# Apply the neon root (and its schema.sql) first.
#
# The app runs a PUBLIC image from GHCR (var.image), built + pushed by the deploy
# workflow — Azure only runs it. (ACR Tasks are blocked on personal/student subs;
# see the module header.) Manual flow, after neon/ + r2/ are applied (state lives
# in the Azure Storage backend — pass `-backend-config=...key=azure.tfstate`):
#   1. Build + push the image yourself, e.g.
#      docker build -t ghcr.io/pcbz/polymnemo:v1.0.0 . && docker push ghcr.io/pcbz/polymnemo:v1.0.0
#      (make the GHCR package Public once, so the app can pull without creds).
#   2. cp terraform.tfvars.example terraform.tfvars   # subscription, image, api_keys, tfstate_*
#   3. terraform init -backend-config=... && terraform apply
#   4. terraform output -raw mcp_endpoint
# Re-deploy new code: push a new image tag and `terraform apply` with the new
# TF_VAR_image.

# Reads the shared Neon and R2 roots' state from the Azure Storage backend, so
# CI (and multiple operators) stay in sync. Apply neon/ and r2/ before this root.
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

module "container_apps" {
  source              = "../modules/container-apps"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_name        = var.service_name
  image               = var.image
  revision_suffix     = var.revision_suffix
  database_url        = data.terraform_remote_state.neon.outputs.connection_uri_pooler
  api_keys            = var.api_keys

  # Media/blob wiring — always on, from the shared r2/ root.
  blob_backend           = "s3"
  blob_bucket            = data.terraform_remote_state.r2.outputs.bucket
  blob_endpoint_url      = data.terraform_remote_state.r2.outputs.endpoint_url
  blob_access_key_id     = data.terraform_remote_state.r2.outputs.access_key_id
  blob_secret_access_key = data.terraform_remote_state.r2.outputs.secret_access_key
}
