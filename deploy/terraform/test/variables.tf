variable "neon_api_key" {
  type        = string
  sensitive   = true
  description = "Neon API key (same account as the prod neon/ root)."
}

variable "azure_subscription_id" {
  type        = string
  description = "Azure subscription id for the test Container App."
}

variable "image" {
  type        = string
  description = "Public GHCR image to run, e.g. ghcr.io/pcbz/polymnemo:v1.1.1. Must contain the POLYMNEMO_LOG_LEVEL support (>= the #102 merge)."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user bearer keys for the test app, \"key1:alice,...\"."
}

variable "service_name" {
  type        = string
  default     = "polymnemo-test"
  description = "Test Container App name (also its resource group / Log Analytics prefix)."
}

variable "location" {
  type        = string
  default     = "westus2"
  description = "Azure region."
}

variable "branch_name" {
  type        = string
  default     = "test"
  description = "Neon branch name to create off the prod default branch."
}

# --- terraform_remote_state coordinates (the shared Azure Storage backend) ----
variable "tfstate_resource_group" {
  type        = string
  description = "Resource group of the tfstate storage account."
}

variable "tfstate_storage_account" {
  type        = string
  description = "tfstate storage account name."
}

variable "tfstate_container" {
  type        = string
  description = "tfstate container name."
}
