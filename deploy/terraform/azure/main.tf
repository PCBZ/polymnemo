# Azure compute: Container Apps, reading the SAME shared Neon connection string
# from the neon root's state — so memories are shared with the GCP deployment.
# Apply the neon root (and its schema.sql) first.
#
# Usually applied by the CI workflow (.github/workflows/deploy.yml). Manual flow,
# after neon/ + r2/ are applied (state lives in the Azure Storage backend — pass
# `-backend-config=...key=azure.tfstate` at init, like the neon/ header shows):
#   1. cp terraform.tfvars.example terraform.tfvars   # subscription, acr_name, api_keys, tfstate_*
#   2. terraform init -backend-config=... && terraform apply   # bootstrap: RG + ACR + env
#   3. az acr build --registry "$(terraform output -raw image_repo | cut -d. -f1)" \
#        --image polymnemo:v1 ../../..
#   4. terraform apply -var "image=$(terraform output -raw image_repo)/polymnemo:v1"
#   5. terraform output -raw mcp_endpoint

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
  acr_name            = var.acr_name
  image               = var.image
  database_url        = data.terraform_remote_state.neon.outputs.connection_uri_pooler
  api_keys            = var.api_keys

  # Media/blob wiring — always on, from the shared r2/ root.
  blob_backend           = "s3"
  blob_bucket            = data.terraform_remote_state.r2.outputs.bucket
  blob_endpoint_url      = data.terraform_remote_state.r2.outputs.endpoint_url
  blob_access_key_id     = data.terraform_remote_state.r2.outputs.access_key_id
  blob_secret_access_key = data.terraform_remote_state.r2.outputs.secret_access_key
}
