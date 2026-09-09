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
  # Local state by default — fine ONLY for a single solo operator. The gcp/ and
  # azure/ roots read this root's state via terraform_remote_state over a local
  # relative path, which requires the roots in one checkout, applied on one
  # machine, this root first. For CI or a second operator a shared remote backend
  # is REQUIRED: switch it here (and in the gcp/ + azure/ remote_state config)
  # and run `terraform init -migrate-state`.
}

# Auth via the CLOUDFLARE_API_TOKEN env var (a token allowed to edit R2 + create
# API tokens).
provider "cloudflare" {}
