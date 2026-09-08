terraform {
  required_version = ">= 1.5"
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.17" # pin: pre-1.0 provider, breaking changes land in minors
    }
  }
  # Local state by default — fine ONLY for a single solo operator. The gcp/ and
  # azure/ roots read this root's state via terraform_remote_state over a local
  # relative path, which requires all three roots in one checkout, applied on one
  # machine, neon first. For CI or a second operator a shared remote backend
  # (GCS / Azure Storage) is REQUIRED, not optional: switch it here (and in the
  # gcp/ + azure/ remote_state config) and run `terraform init -migrate-state`.
}

provider "neon" {
  api_key = var.neon_api_key
}
