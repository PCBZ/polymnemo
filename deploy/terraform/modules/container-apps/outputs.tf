output "service_url" {
  description = "Container App HTTPS URL."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/mcp"
}
