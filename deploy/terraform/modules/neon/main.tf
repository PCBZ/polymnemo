# A Neon project: Postgres + pgvector, with a default branch/database/role.
# Apply scripts/schema.sql to it once (see the root runbook).
resource "neon_project" "this" {
  name       = var.name
  region_id  = var.region_id
  pg_version = var.pg_version
}
