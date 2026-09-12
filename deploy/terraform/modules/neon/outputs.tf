output "connection_uri" {
  description = "Direct (non-pooled) connection string — for psql / schema migration."
  value       = neon_project.this.connection_uri
  sensitive   = true
}

output "connection_uri_pooler" {
  description = "Pooled connection string — for the application (Cloud Run)."
  value       = neon_project.this.connection_uri_pooler
  sensitive   = true
}

# Exposed so a test root can branch off this project and build the branch DSN.
output "project_id" {
  description = "Neon project id."
  value       = neon_project.this.id
}

output "default_branch_id" {
  description = "Default (prod) branch id — parent for test branches."
  value       = neon_project.this.default_branch_id
}

output "database_user" {
  description = "Default database role."
  value       = neon_project.this.database_user
}

output "database_name" {
  description = "Default database name."
  value       = neon_project.this.database_name
}
