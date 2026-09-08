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
