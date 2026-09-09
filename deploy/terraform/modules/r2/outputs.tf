output "bucket" {
  description = "R2 bucket name for media blobs."
  value       = cloudflare_r2_bucket.media.name
}

output "endpoint_url" {
  description = "S3 endpoint for this account's R2 (POLYMNEMO_BLOB_ENDPOINT_URL)."
  value       = "https://${var.cf_account_id}.r2.cloudflarestorage.com"
}

output "access_key_id" {
  description = "R2 S3 access key id (the API token id)."
  value       = cloudflare_api_token.r2.id
}

output "secret_access_key" {
  description = "R2 S3 secret access key (sha256 of the API token value)."
  value       = sha256(cloudflare_api_token.r2.value)
  sensitive   = true
}
