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

data "terraform_remote_state" "neon" {
  backend = "local"
  config = {
    path = "../neon/terraform.tfstate"
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
}
