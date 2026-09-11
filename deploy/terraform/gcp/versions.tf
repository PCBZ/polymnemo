terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Own state in the same Azure Storage backend as the rest, so the backup GCP
  # deploy workflow can persist it. Coordinates via `-backend-config` at init.
  backend "azurerm" {
    key = "gcp.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
