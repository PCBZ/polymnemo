terraform {
  required_version = ">= 1.5"
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.17" # pin: pre-1.0 provider, breaking changes land in minors
    }
  }
  # State lives in Azure Storage so CI (and multiple operators) share it. The
  # storage account/container/key come from `-backend-config` at init time (the
  # deploy workflow and the bootstrap script pass them), so nothing here is
  # environment-specific. Bootstrap the storage once with
  # scripts/bootstrap-tfstate-azure.sh.
  backend "azurerm" {
    key = "neon.tfstate"
  }
}

provider "neon" {
  api_key = var.neon_api_key
}
