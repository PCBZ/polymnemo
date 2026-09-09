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
  description = "Cloud Run service name (also the Artifact Registry repo id)."
}

variable "image" {
  type        = string
  default     = ""
  description = "AR image URI incl. tag. Empty on the bootstrap apply (service skipped)."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

variable "github_owner" {
  type        = string
  default     = "PCBZ"
  description = "GitHub owner of the repo whose Actions variable MCP_ENDPOINT gets the deployed /mcp URL (for the registry-publish workflow)."
}

variable "github_repository" {
  type        = string
  default     = "polymnemo"
  description = "GitHub repository name under github_owner."
}

variable "publish_mcp_endpoint" {
  type        = bool
  default     = true
  description = "Write the deployed /mcp URL into the MCP_ENDPOINT Actions variable (for registry-publish). The BACKUP GCP workflow sets this false so it doesn't hijack the primary (Azure) endpoint, and so the github provider needs no token."
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

