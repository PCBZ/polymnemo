output "connection_uri" {
  description = "Direct (non-pooled) connection string — for `psql -f scripts/schema.sql`."
  value       = module.neon.connection_uri
  sensitive   = true
}

output "connection_uri_pooler" {
  description = "Pooled connection string — consumed by the gcp/ and azure/ roots."
  value       = module.neon.connection_uri_pooler
  sensitive   = true
}

# Consumed by the test/ root to branch off this project for a DEBUG test env.
output "project_id" {
  description = "Neon project id."
  value       = module.neon.project_id
}

output "default_branch_id" {
  description = "Default (prod) branch id."
  value       = module.neon.default_branch_id
}

output "database_user" {
  description = "Default database role."
  value       = module.neon.database_user
}

output "database_name" {
  description = "Default database name."
  value       = module.neon.database_name
}
