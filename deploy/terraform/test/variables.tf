variable "neon_api_key" {
  type        = string
  sensitive   = true
  description = "Neon API key (same account as the prod neon/ root)."
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
