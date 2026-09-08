terraform {
  required_version = ">= 1.5"
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = ">= 0.6.0"
    }
  }
  # Local state by default. Because BOTH the gcp/ and azure/ roots read this
  # root's state (terraform_remote_state), a shared remote backend (GCS / Azure
  # Storage) is worth adopting for team use — switch it here + init -migrate-state.
}

provider "neon" {
  api_key = var.neon_api_key
}
