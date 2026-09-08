output "image_repo" {
  description = "Push the image here (append :TAG)."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.polymnemo.repository_id}"
}

output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = google_service_account.runtime.email
}

output "service_url" {
  description = "Cloud Run HTTPS URL. Empty until the service is created (image set)."
  value       = length(google_cloud_run_v2_service.polymnemo) > 0 ? google_cloud_run_v2_service.polymnemo[0].uri : ""
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = length(google_cloud_run_v2_service.polymnemo) > 0 ? "${google_cloud_run_v2_service.polymnemo[0].uri}/mcp" : ""
}
