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
  default     = 16
  description = "Postgres major version."
}
