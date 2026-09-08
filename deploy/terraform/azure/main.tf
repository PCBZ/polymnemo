# Azure compute: Container Apps, reading the SAME shared Neon connection string
# from the neon root's state — so memories are shared with the GCP deployment.
# Apply the neon root (and its schema.sql) first.
#
# Usage:
#   1. (once) apply deploy/terraform/neon + its schema.sql
#   2. az login   (and set var.azure_subscription_id)
#   3. cp terraform.tfvars.example terraform.tfvars   # subscription, acr_name, api_keys
#   4. terraform init && terraform apply               # bootstrap: RG + ACR + env
#   5. REPO="$(terraform output -raw image_repo)"      # <acr>.azurecr.io
#      az acr build --registry "$(echo "$REPO" | cut -d. -f1)" --image polymnemo:v1 ../../../
#   6. terraform apply -var "image=$REPO/polymnemo:v1"
#   7. terraform output -raw mcp_endpoint

# Reads the shared Neon root's state over a LOCAL relative path — this requires
# all three roots in one checkout, applied on one machine, neon applied first.
# For CI or a second operator, a shared remote backend is REQUIRED (see neon/versions.tf).
data "terraform_remote_state" "neon" {
  backend = "local"
  config = {
    path = "../neon/terraform.tfstate"
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
}
