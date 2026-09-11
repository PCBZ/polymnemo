output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = google_service_account.runtime.email
}

output "service_url" {
  description = "Cloud Run HTTPS URL."
  value       = google_cloud_run_v2_service.polymnemo.uri
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = "${google_cloud_run_v2_service.polymnemo.uri}/mcp"
}
