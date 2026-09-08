output "image_repo" {
  description = "ACR login server. Build/push with `az acr build --registry <acr> --image polymnemo:v1 .`"
  value       = azurerm_container_registry.acr.login_server
}

output "service_url" {
  description = "Container App HTTPS URL. Empty until the app is created (image set)."
  value       = length(azurerm_container_app.this) > 0 ? "https://${azurerm_container_app.this[0].ingress[0].fqdn}" : ""
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = length(azurerm_container_app.this) > 0 ? "https://${azurerm_container_app.this[0].ingress[0].fqdn}/mcp" : ""
}
