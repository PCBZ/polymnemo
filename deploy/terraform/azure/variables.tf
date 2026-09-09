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

variable "cf_account_id" {
  type        = string
  default     = ""
  description = "Cloudflare account id for the R2 media bucket. Empty (default) leaves media/blob storage OFF; set it to provision R2 and turn the media tools on."
}

variable "media_bucket_name" {
  type        = string
  default     = "polymnemo-media"
  description = "R2 bucket name for media blobs (used only when cf_account_id is set)."
}
