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
