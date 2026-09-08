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
  description = "Cloud Run service name (also the Artifact Registry repo id)."
}

variable "image" {
  type        = string
  description = "Full Artifact Registry image URI incl. tag. Empty on the bootstrap apply (the service is then skipped)."
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
