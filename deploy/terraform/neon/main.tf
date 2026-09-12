# The single, SHARED Neon project (Postgres + pgvector). Both the gcp/ and
# azure/ roots read its connection string via terraform_remote_state, so a
# memory written from one cloud is recallable from the other.
#
# Usually applied by the CI workflow (.github/workflows/deploy.yml). For a manual
# apply, state lives in the Azure Storage backend — pass its coordinates at init
# (bootstrap it first with scripts/bootstrap-tfstate-azure.sh):
#   1. cp terraform.tfvars.example terraform.tfvars   # neon_api_key
#   2. terraform init \
#        -backend-config=resource_group_name=<rg> \
#        -backend-config=storage_account_name=<sa> \
#        -backend-config=container_name=tfstate \
#        -backend-config=key=neon.tfstate
#   3. terraform apply
#   4. psql "$(terraform output -raw connection_uri)" -f ../../../scripts/schema.sql
#
# Then apply the gcp/ and/or azure/ roots (they read this root's state).

module "neon" {
  source                    = "../modules/neon"
  name                      = var.name
  region_id                 = var.neon_region_id
  pg_version                = 17
  history_retention_seconds = var.history_retention_seconds
}
