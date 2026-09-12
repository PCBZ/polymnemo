output "mcp_endpoint" {
  description = "The test MCP endpoint (DEBUG logging on)."
  value       = module.container_apps.mcp_endpoint
}

output "service_url" {
  description = "Test Container App HTTPS URL."
  value       = module.container_apps.service_url
}

output "log_analytics_workspace" {
  description = "Query the #96 observe logs here (see README.md)."
  value       = "${var.service_name}-logs"
}
