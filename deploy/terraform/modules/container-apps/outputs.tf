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

