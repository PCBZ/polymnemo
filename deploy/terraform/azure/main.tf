# Azure compute: Container Apps, reading the SAME shared Neon connection string
# from the neon root's state — so memories are shared with the GCP deployment.
# Apply the neon root (and its schema.sql) first.
#
# Usually applied by the CI workflow (.github/workflows/deploy.yml). One apply
# does everything — Terraform builds the image IN ACR (no `az acr build`) and
# deploys it. Manual flow, after neon/ + r2/ are applied (state lives in the
# Azure Storage backend — pass `-backend-config=...key=azure.tfstate` at init):
#   1. cp terraform.tfvars.example terraform.tfvars   # subscription, acr_name, api_keys, tfstate_*
#      export TF_VAR_context_access_token=<a GitHub token that can clone the repo>
#   2. terraform init -backend-config=... && terraform apply
#   3. terraform output -raw mcp_endpoint
# Re-deploy new code: `terraform apply -replace=module.container_apps.azurerm_container_registry_task_schedule_run_now.build`

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
  source               = "../modules/container-apps"
  resource_group_name  = var.resource_group_name
  location             = var.location
  service_name         = var.service_name
  acr_name             = var.acr_name
  image_tag            = var.image_tag
  git_context          = var.git_context
  context_access_token = var.context_access_token
  database_url         = data.terraform_remote_state.neon.outputs.connection_uri_pooler
  api_keys             = var.api_keys

  # Media/blob wiring — always on, from the shared r2/ root.
  blob_backend           = "s3"
  blob_bucket            = data.terraform_remote_state.r2.outputs.bucket
  blob_endpoint_url      = data.terraform_remote_state.r2.outputs.endpoint_url
  blob_access_key_id     = data.terraform_remote_state.r2.outputs.access_key_id
  blob_secret_access_key = data.terraform_remote_state.r2.outputs.secret_access_key
}
