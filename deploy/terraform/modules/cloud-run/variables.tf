variable "project_id" {
  type        = string
  description = "GCP project id."
}

variable "region" {
  type        = string
  description = "Cloud Run region."
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
}

variable "image" {
  type        = string
  description = "Full public image reference incl. tag, e.g. ghcr.io/pcbz/polymnemo:v1.0.0 (Cloud Run pulls it directly)."
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "Postgres pooled connection string, injected as POLYMNEMO_DATABASE_URL."
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
  description = "R2 S3 access key id, injected as POLYMNEMO_BLOB_ACCESS_KEY_ID."
}

variable "blob_secret_access_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "R2 S3 secret access key, injected as POLYMNEMO_BLOB_SECRET_ACCESS_KEY."
}

variable "memory" {
  type        = string
  default     = "1Gi"
  description = "Memory per instance (2Gi if the first embed OOMs)."
}

variable "cpu" {
  type        = string
  default     = "1"
  description = "vCPU per instance."
}

variable "max_instances" {
  type        = number
  default     = 3
  description = "Max instances (min is 0 for scale-to-zero)."
}

variable "concurrency" {
  type        = number
  default     = 8
  description = "Requests per instance; keep modest per vCPU (embedding is CPU-bound)."
}
