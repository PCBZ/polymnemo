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

variable "image" {
  type        = string
  description = "Full container image reference to run, e.g. ghcr.io/pcbz/polymnemo:v1.0.0. Built + pushed by the deploy workflow; must be publicly pullable. The workflow sets it to the triggering tag/SHA."
}

variable "revision_suffix" {
  type        = string
  default     = ""
  description = "Per-deploy unique value (the workflow sets the CI run id) that forces a fresh Container App revision even when the image ref is unchanged. Empty = Azure auto-generates one."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

# --- Remote-state backend (Azure Storage) — where the neon/ and r2/ roots' state
# lives, so this root can read it via terraform_remote_state. Same values used at
# `terraform init -backend-config`. The deploy workflow sets these from GitHub
# variables the bootstrap script created. ------------------------------------
variable "tfstate_resource_group" {
  type        = string
  description = "Resource group holding the Terraform-state storage account."
}

variable "tfstate_storage_account" {
  type        = string
  description = "Storage account holding the Terraform state."
}

variable "tfstate_container" {
  type        = string
  default     = "tfstate"
  description = "Blob container holding the Terraform state."
}

