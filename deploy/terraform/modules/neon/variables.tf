variable "name" {
  type        = string
  description = "Neon project name."
}

variable "region_id" {
  type        = string
  description = "Neon region id, e.g. aws-us-west-2."
}

variable "pg_version" {
  type        = number
  default     = 17
  description = "Postgres major version."
}

variable "history_retention_seconds" {
  type        = number
  default     = 21600
  description = "Point-in-time restore window. The Neon Free plan caps this at 21600 (6h); paid plans allow more."
}
