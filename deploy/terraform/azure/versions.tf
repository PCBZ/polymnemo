terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # State in Azure Storage (shared with CI); coordinates via `-backend-config`
  # at init. Bootstrap once with scripts/bootstrap-tfstate-azure.sh.
  backend "azurerm" {
    key = "azure.tfstate"
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.azure_subscription_id
}
