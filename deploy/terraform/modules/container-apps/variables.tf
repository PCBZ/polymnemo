variable "resource_group_name" {
  type        = string
  description = "Resource group to create for polymnemo."
}

variable "location" {
  type        = string
  description = "Azure region, e.g. westus2."
}

variable "service_name" {
  type        = string
  description = "Container App name (and prefix for the environment / identity)."
}

variable "image" {
  type        = string
  description = "Full container image reference the app runs, e.g. ghcr.io/pcbz/polymnemo:v1.0.0. Must be publicly pullable (no registry credentials are configured)."
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "Postgres pooled connection string (from the shared Neon), injected as POLYMNEMO_DATABASE_URL."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

# --- Media / blob storage (R2). "none" leaves the media tools off. ------------
variable "blob_backend" {
  type        = string
  default     = "none"
  description = "\"none\" (media off) or \"s3\" (R2). When \"s3\", the four blob_* below are injected."
}

variable "blob_bucket" {
  type        = string
  default     = ""
  description = "R2 bucket name, injected as POLYMNEMO_BLOB_BUCKET."
}

variable "blob_endpoint_url" {
  type        = string
  default     = ""
  description = "R2 S3 endpoint, injected as POLYMNEMO_BLOB_ENDPOINT_URL."
}

variable "blob_access_key_id" {
  type        = string
  default     = ""
  sensitive   = true
  description = "R2 S3 access key id, injected (as a secret) into POLYMNEMO_BLOB_ACCESS_KEY_ID."
}

variable "blob_secret_access_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "R2 S3 secret access key, injected (as a secret) into POLYMNEMO_BLOB_SECRET_ACCESS_KEY."
}

variable "cpu" {
  type        = number
  default     = 1.0
  description = "vCPU per replica. Container Apps fixes cpu:memory at 1:2 (1.0 -> 2Gi)."
}

variable "memory" {
  type        = string
  default     = "2Gi"
  description = "Memory per replica; must match the cpu:memory 1:2 ratio."
}

variable "min_replicas" {
  type        = number
  default     = 0
  description = "0 = scale to zero when idle."
}

variable "max_replicas" {
  type        = number
  default     = 3
  description = "Max replicas under load."
}
