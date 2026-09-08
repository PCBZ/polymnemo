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

variable "acr_name" {
  type        = string
  description = "Azure Container Registry name — globally unique, 5-50 alphanumeric."
}

variable "image" {
  type        = string
  description = "Full ACR image ref incl. tag (e.g. myacr.azurecr.io/polymnemo:v1). Empty on the bootstrap apply — the Container App is then skipped."
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
