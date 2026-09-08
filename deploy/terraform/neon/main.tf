# The single, SHARED Neon project (Postgres + pgvector). Both the gcp/ and
# azure/ roots read its connection string via terraform_remote_state, so a
# memory written from one cloud is recallable from the other.
#
# Usage:
#   1. cp terraform.tfvars.example terraform.tfvars   # neon_api_key
#   2. terraform init && terraform apply
#   3. psql "$(terraform output -raw connection_uri)" -f ../../../scripts/schema.sql
#
# Then apply the gcp/ and/or azure/ roots (they read this root's state).

module "neon" {
  source     = "../modules/neon"
  name       = var.name
  region_id  = var.neon_region_id
  pg_version = 16
}
