# The TEST deployment: same structure as azure/, isolated data.
#
# What differs from prod, and only this:
#   database_url  <- the Neon BRANCH from test/, not the prod project
#   blob bucket   <- the bucket from r2-test/, not the shared prod one
#   api_keys      <- its own, so a prod key does not open test (or the reverse)
#
# What it deliberately SHARES with prod: the resource group, the Log Analytics
# workspace and the Container App Environment. Not a shortcut — the subscription
# allows one managed environment per region (westus2 reports 1/1), so a second
# one here is impossible. Sharing them costs nothing that matters: neither holds
# application data, and the log query already scopes by ContainerAppName_s.

data "terraform_remote_state" "prod" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "azure.tfstate"
  }
}

# The isolated database: a copy-on-write Neon branch of prod, created and kept
# schema-current by the `test` job in deploy.yml.
data "terraform_remote_state" "neon_test" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "test.tfstate"
  }
}

data "terraform_remote_state" "r2_test" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "r2-test.tfstate"
  }
}

module "container_apps" {
  source          = "../modules/container-apps"
  service_name    = var.service_name
  image           = var.image
  revision_suffix = var.revision_suffix

  # Attach to prod's platform rather than creating a second one.
  resource_group_name         = var.resource_group_name
  location                    = var.location
  existing_environment_id     = data.terraform_remote_state.prod.outputs.environment_id
  existing_environment_name   = data.terraform_remote_state.prod.outputs.environment_name
  existing_log_workspace_name = data.terraform_remote_state.prod.outputs.log_workspace_name

  # --- The isolation ---------------------------------------------------------
  database_url = data.terraform_remote_state.neon_test.outputs.database_url
  api_keys     = var.api_keys

  blob_backend           = "s3"
  blob_bucket            = data.terraform_remote_state.r2_test.outputs.bucket
  blob_endpoint_url      = data.terraform_remote_state.r2_test.outputs.endpoint_url
  blob_access_key_id     = data.terraform_remote_state.r2_test.outputs.access_key_id
  blob_secret_access_key = data.terraform_remote_state.r2_test.outputs.secret_access_key

  oauth_client_id             = var.oauth_client_id
  oauth_client_secret         = var.oauth_client_secret
  oauth_allowed_redirect_uris = var.oauth_allowed_redirect_uris
}
