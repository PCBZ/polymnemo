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
