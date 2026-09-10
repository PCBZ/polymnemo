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

variable "image_tag" {
  type        = string
  default     = "v1"
  description = "Tag for the image Terraform builds in ACR and runs (polymnemo:<tag>)."
}

variable "git_context" {
  type        = string
  default     = "https://github.com/PCBZ/polymnemo.git#main"
  description = "Git ref the ACR build task clones (repo#ref). The deploy workflow sets it to the triggering tag or branch, so a tagged deploy builds that tag."
}

variable "context_access_token" {
  type        = string
  sensitive   = true
  description = "Token for the ACR build task's Git context. Required even for a public repo; the workflow passes the short-lived GITHUB_TOKEN."
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

