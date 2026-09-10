variable "neon_api_key" {
  type        = string
  sensitive   = true
  description = "Neon API key (Neon console → Account settings → API keys)."
}

variable "neon_region_id" {
  type        = string
  default     = "aws-us-west-2"
  description = "Neon region id, e.g. aws-us-west-2."
}

variable "name" {
  type        = string
  default     = "polymnemo"
  description = "Neon project name."
}

variable "history_retention_seconds" {
  type        = number
  default     = 21600
  description = "Point-in-time restore window. The Neon Free plan caps this at 21600 (6h); raise on paid plans."
}
