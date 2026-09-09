variable "cf_account_id" {
  type        = string
  description = "Cloudflare account id that owns the R2 bucket."
}

variable "bucket_name" {
  type        = string
  default     = "polymnemo-media"
  description = "R2 bucket name for media blobs."
}

variable "location" {
  type        = string
  default     = "WNAM"
  description = "R2 location hint (WNAM | ENAM | WEUR | EEUR | APAC). Put it near your compute region to cut latency."
}

variable "token_name" {
  type        = string
  default     = "polymnemo-r2"
  description = "Name of the R2-scoped API token Terraform creates for S3 access."
}

# Escape hatch for the known v5 403 on the derived credentials (#6626): set BOTH
# to pre-made R2 S3 credentials (create them in the dashboard: R2 -> Manage R2
# API Tokens) and Terraform skips creating/deriving a token, using these instead.
# Leave empty (default) to auto-derive.
variable "access_key_id" {
  type        = string
  default     = ""
  description = "Optional pre-made R2 S3 access key id. When set together with secret_access_key, bypasses the token derivation."
}

variable "secret_access_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Optional pre-made R2 S3 secret access key. Pair with access_key_id to bypass the token derivation."
}
