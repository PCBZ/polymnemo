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

variable "media_enabled" {
  type        = bool
  default     = false
  description = "Turn the media tools on by reading the shared r2/ root's state (the bucket + S3 creds). Requires the r2/ root applied first. Default false = media off (no Cloudflare dependency)."
}
