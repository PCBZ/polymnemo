output "service_url" {
  description = "Container App HTTPS URL. Empty until the app is created (image set)."
  value       = module.container_apps.service_url
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = module.container_apps.mcp_endpoint
}

output "media_bucket" {
  description = "Shared R2 media bucket name (from the r2/ root)."
  value       = data.terraform_remote_state.r2.outputs.bucket
}

output "app_name" {
  description = "Container App name, for scoping a Log Analytics query to this app."
  value       = module.container_apps.app_name
}

output "log_workspace_id" {
  description = "Log Analytics customer id, for the smoke workflow's log check."
  value       = module.container_apps.log_workspace_id
}

# --- Consumed by the azure-test/ root, which shares this platform ------------
output "environment_id" {
  description = "Container App Environment id — the test root attaches to it."
  value       = module.container_apps.environment_id
}

output "environment_name" {
  description = "Container App Environment name."
  value       = module.container_apps.environment_name
}

output "log_workspace_name" {
  description = "Log Analytics workspace name (ARM resource, not the query GUID)."
  value       = module.container_apps.log_workspace_name
}
