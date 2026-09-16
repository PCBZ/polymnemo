output "service_url" {
  description = "Test Container App HTTPS URL — what the smoke gate points at."
  value       = module.container_apps.service_url
}

output "mcp_endpoint" {
  description = "The test deployment's MCP endpoint."
  value       = module.container_apps.mcp_endpoint
}

output "app_name" {
  description = "Container App name. The log query scopes on this, which is what keeps test and prod lines apart in the shared workspace."
  value       = module.container_apps.app_name
}

output "log_workspace_id" {
  description = "Log Analytics customer id — the same workspace prod uses."
  value       = module.container_apps.log_workspace_id
}
