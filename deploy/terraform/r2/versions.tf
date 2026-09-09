terraform {
  required_version = ">= 1.5"
  required_providers {
    # Float within v5 so we pick up fixes; the R2 S3-cred derivation has had
    # provider-version churn (see modules/r2 + cloudflare/terraform-provider-cloudflare#6626).
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
  # State in Azure Storage (shared with CI); coordinates via `-backend-config`
  # at init. Bootstrap once with scripts/bootstrap-tfstate-azure.sh.
  backend "azurerm" {
    key = "r2.tfstate"
  }
}

# Auth via the CLOUDFLARE_API_TOKEN env var (a token allowed to edit R2 + create
# API tokens).
provider "cloudflare" {}
