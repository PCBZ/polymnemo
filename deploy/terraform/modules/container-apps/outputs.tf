output "service_url" {
  description = "Container App HTTPS URL."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/mcp"
}

output "app_name" {
  description = "Container App name, for scoping a Log Analytics query to this app."
  value       = azurerm_container_app.this.name
}

output "log_workspace_id" {
  description = "Log Analytics *customer* id (the GUID `az monitor log-analytics query -w` takes), not the ARM resource id."
  value       = local.log_workspace_id
}

# --- For a second app attaching to this platform -----------------------------
output "environment_id" {
  description = "Container App Environment id, for another root's existing_environment_id."
  value       = local.environment_id
}

output "environment_name" {
  description = "Container App Environment name."
  value       = local.create_platform ? azurerm_container_app_environment.this[0].name : var.existing_environment_name
}

output "log_workspace_name" {
  description = "Log Analytics workspace NAME (the ARM resource), distinct from log_workspace_id, which is the query GUID."
  value       = local.create_platform ? azurerm_log_analytics_workspace.this[0].name : var.existing_log_workspace_name
}
