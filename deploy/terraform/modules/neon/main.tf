# A Neon project: Postgres + pgvector, with a default branch/database/role.
# Apply scripts/schema.sql to it once (see the root runbook).
resource "neon_project" "this" {
  name       = var.name
  region_id  = var.region_id
  pg_version = var.pg_version
  # The provider defaults this to 86400 (1 day), which the Neon Free plan
  # rejects ("exceeds allowed maximum ... max: 21600"). Cap it at the free-tier
  # ceiling (6h) so a clean apply works out of the box; override on paid plans.
  history_retention_seconds = var.history_retention_seconds
}
