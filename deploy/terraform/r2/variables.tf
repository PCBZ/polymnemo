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
  description = "R2 location hint (WNAM | ENAM | WEUR | EEUR | APAC). Put it near your compute region(s)."
}

variable "token_name" {
  type        = string
  default     = "polymnemo-r2"
  description = "Name of the R2-scoped API token Terraform creates for S3 access."
}
