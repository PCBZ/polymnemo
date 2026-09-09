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
    # Float within v5 so we pick up fixes; the R2 S3-cred derivation has had
    # provider-version churn (see modules/r2 + cloudflare/terraform-provider-cloudflare#6626).
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.azure_subscription_id
}

# R2 media bucket + S3 creds. Only exercised when var.cf_account_id is set, so a
# DB-only deploy needs no Cloudflare auth. When used, auth via the
# CLOUDFLARE_API_TOKEN env var (a token allowed to edit R2 + create API tokens).
provider "cloudflare" {}
