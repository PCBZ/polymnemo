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
