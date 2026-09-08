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
