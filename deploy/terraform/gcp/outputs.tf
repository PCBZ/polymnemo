output "service_url" {
  description = "Cloud Run HTTPS URL."
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
  description = "Shared R2 media bucket name (from the r2/ root)."
  value       = data.terraform_remote_state.r2.outputs.bucket
}
