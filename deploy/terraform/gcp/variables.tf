variable "project_id" {
  type        = string
  description = "GCP project id to deploy into."
}

variable "region" {
  type        = string
  default     = "us-west1"
  description = "Cloud Run region."
}

variable "service_name" {
  type        = string
  default     = "polymnemo"
  description = "Cloud Run service name."
}

variable "image" {
  type        = string
  description = "Full public image reference incl. tag, e.g. ghcr.io/pcbz/polymnemo:v1.0.0. The SAME image Azure runs; Cloud Run pulls it from GHCR directly."
}

variable "revision_suffix" {
  type        = string
  default     = ""
  description = "Per-deploy unique value (the workflow sets the CI run id) that forces a fresh Cloud Run revision even when the image ref is unchanged. Empty = Cloud Run auto-names it."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

# --- Remote-state backend (Azure Storage) — the shared neon/ + r2/ state lives
# here, so this root reads it from there (needs ARM_* creds to read). Same values
# used at `terraform init -backend-config`. ----------------------------------
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
