variable "azure_subscription_id" {
  type        = string
  description = "Azure subscription id to deploy into."
}

variable "location" {
  type        = string
  default     = "westus2"
  description = "Azure region. Put it near the Neon region to cut DB latency."
}

variable "resource_group_name" {
  type        = string
  default     = "polymnemo-rg"
  description = "Resource group to create."
}

variable "service_name" {
  type        = string
  default     = "polymnemo"
  description = "Container App name."
}

variable "acr_name" {
  type        = string
  description = "Azure Container Registry name — globally unique, 5-50 alphanumeric (e.g. polymnemoacr123)."
}

variable "image" {
  type        = string
  default     = ""
  description = "ACR image ref incl. tag. Empty on the bootstrap apply (app skipped)."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

variable "media_enabled" {
  type        = bool
  default     = false
  description = "Turn the media tools on by reading the shared r2/ root's state (the bucket + S3 creds). Requires the r2/ root applied first. Default false = media off (no Cloudflare dependency)."
}
