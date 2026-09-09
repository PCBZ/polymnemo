terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    # Float within v5 so we pick up fixes; the R2 S3-cred derivation has had
    # provider-version churn (see modules/r2 + cloudflare/terraform-provider-cloudflare#6626).
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Used to write the deployed endpoint into a GitHub Actions variable so the
# registry-publish workflow can pick it up. Auth via the GITHUB_TOKEN env var
# (a token with repo + actions:write on the repo below) at apply time.
provider "github" {
  owner = var.github_owner
}

# R2 media bucket + S3 creds. Only exercised when var.cf_account_id is set, so a
# DB-only deploy needs no Cloudflare auth. When used, auth via the
# CLOUDFLARE_API_TOKEN env var (a token allowed to edit R2 + create API tokens).
provider "cloudflare" {}
