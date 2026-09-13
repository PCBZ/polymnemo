terraform {
  required_version = ">= 1.5"
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.17"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
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

provider "azurerm" {
  features {
    # Default is soft-delete (14 days), which would resurrect the workspace in
    # its ORIGINAL region when recreated under the same name — so a region move
    # would silently drag it back. Test logs are disposable; drop them for real.
    log_analytics_workspace {
      permanently_delete_on_destroy = true
    }
  }
  subscription_id = var.azure_subscription_id
}
