output "image_repo" {
  description = "ACR login server (<acr>.azurecr.io). Build/push with `az acr build`."
  value       = module.container_apps.image_repo
}

output "service_url" {
  description = "Container App HTTPS URL. Empty until the app is created (image set)."
  value       = module.container_apps.service_url
}

output "mcp_endpoint" {
  description = "The MCP endpoint clients connect to."
  value       = module.container_apps.mcp_endpoint
}

output "media_bucket" {
  description = "R2 media bucket name, or empty when media is disabled."
  value       = try(module.r2[0].bucket, "")
}
