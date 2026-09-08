terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    neon = {
      source  = "kislerdm/neon"
      version = ">= 0.6.0"
    }
  }
  # State backend: local by default (terraform.tfstate on disk, gitignored).
  # To share/lock state, switch to a GCS bucket:
  #   backend "gcs" { bucket = "your-tfstate-bucket" prefix = "polymnemo" }
  # then run `terraform init -migrate-state`.
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "neon" {
  api_key = var.neon_api_key
}
