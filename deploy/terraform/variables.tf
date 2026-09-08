variable "project_id" {
  type        = string
  description = "GCP project id to deploy into."
}

variable "region" {
  type        = string
  default     = "us-west1"
  description = "Cloud Run region. Put it near your Neon project to cut DB latency."
}

variable "service_name" {
  type        = string
  default     = "polymnemo"
  description = "Cloud Run service name (also the Artifact Registry repo id)."
}

variable "image" {
  type        = string
  default     = ""
  description = <<-EOT
    Full Artifact Registry image URI including tag, e.g.
    us-west1-docker.pkg.dev/PROJECT/polymnemo/polymnemo:v1

    Leave empty for the first ("bootstrap") apply — the Cloud Run service and its
    public-invoker binding are then skipped, so you can create the registry +
    secrets, push an image, and only then apply again with the image set.
  EOT
}

# Operational knobs (memory / cpu / max_instances / concurrency) live in
# modules/cloud-run with sensible defaults — tune them there if needed.

variable "neon_api_key" {
  type        = string
  sensitive   = true
  description = "Neon API key (Neon console → Account settings → API keys). Terraform uses it to create/manage the Neon project."
}

variable "neon_region_id" {
  type        = string
  default     = "aws-us-west-2"
  description = "Neon region. Match it to var.region (Cloud Run) to keep DB latency low."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys as \"key1:alice,key2:bob\". Sensitive — stored in state and the Cloud Run env; keep state private."
}
