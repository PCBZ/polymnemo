terraform {
  required_version = ">= 1.5"
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.17"
    }
  }

  # Shares the Azure Storage backend with the other roots; coordinates via
  # `-backend-config` at init. Its own state key so it never clashes with prod.
  backend "azurerm" {
    key = "test.tfstate"
  }
}

provider "neon" {
  api_key = var.neon_api_key
}
