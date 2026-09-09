output "image_repo" {
  description = "Push the image here (append :TAG) via `gcloud builds submit`."
  value       = module.cloud_run.image_repo
}

output "service_url" {
  description = "Cloud Run HTTPS URL. Empty until the service is created (image set)."
  value       = module.cloud_run.service_url
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = module.cloud_run.mcp_endpoint
}

output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = module.cloud_run.runtime_service_account
}

output "media_bucket" {
  description = "R2 media bucket name, or empty when media is disabled."
  value       = try(module.r2[0].bucket, "")
}
