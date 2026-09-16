output "bucket" {
  description = "R2 bucket name — consumed by the azure-test/ root."
  value       = module.r2.bucket
}

output "endpoint_url" {
  description = "R2 S3 endpoint — consumed by the azure-test/ root."
  value       = module.r2.endpoint_url
}

output "access_key_id" {
  description = "R2 S3 access key id — consumed by the azure-test/ root."
  value       = module.r2.access_key_id
}

output "secret_access_key" {
  description = "R2 S3 secret access key — consumed by the azure-test/ root."
  value       = module.r2.secret_access_key
  sensitive   = true
}
