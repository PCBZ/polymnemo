output "image_repo" {
  description = "Push the image here (append :TAG), e.g. with `gcloud builds submit`."
  value       = module.cloud_run.image_repo
}

output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = module.cloud_run.runtime_service_account
}

output "service_url" {
  description = "Cloud Run HTTPS URL. Empty until the service is created (image set)."
  value       = module.cloud_run.service_url
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = module.cloud_run.mcp_endpoint
}

output "database_url_direct" {
  description = "Neon DIRECT (non-pooled) connection string — for `psql -f scripts/schema.sql`."
  value       = module.neon.connection_uri
  sensitive   = true
}

output "database_url_pooler" {
  description = "Neon POOLED connection string — what the Cloud Run service uses."
  value       = module.neon.connection_uri_pooler
  sensitive   = true
}
