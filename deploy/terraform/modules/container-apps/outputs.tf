output "image_repo" {
  description = "ACR login server that holds the Terraform-built image."
  value       = azurerm_container_registry.acr.login_server
}

output "service_url" {
  description = "Container App HTTPS URL."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}/mcp"
}
