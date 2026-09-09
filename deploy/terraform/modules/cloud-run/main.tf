# polymnemo as a Cloud Run service: APIs, Artifact Registry, a least-privilege
# runtime service account, the service itself, and public access. The DB URL and
# API keys arrive as inputs (from the neon module / root) and are injected as env.

# --- APIs -------------------------------------------------------------------
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Artifact Registry (Cloud Build pushes the image here) ------------------
resource "google_artifact_registry_repository" "polymnemo" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "polymnemo container images"
  depends_on    = [google_project_service.services]

  # Keep only the 3 most recent image versions; delete the rest so image
  # storage can't creep up over time. KEEP wins over DELETE, so this nets to
  # "retain the newest 3, delete everything older".
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-latest-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  cleanup_policies {
    id     = "delete-older"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }
}

# --- Least-privilege runtime service account --------------------------------
resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "polymnemo Cloud Run runtime"
}

# --- Cloud Run service (skipped on the bootstrap apply, when image == "") ----
resource "google_cloud_run_v2_service" "polymnemo" {
  count               = var.image == "" ? 0 : 1
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = var.concurrency
    timeout                          = "120s"

    scaling {
      min_instance_count = 0 # scale to zero when idle
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        limits            = { cpu = var.cpu, memory = var.memory }
        cpu_idle          = true # request-based billing: CPU only during requests -> $0 when idle
        startup_cpu_boost = true # snappier cold start while the model loads
      }

      env {
        name  = "POLYMNEMO_DATABASE_URL"
        value = var.database_url
      }
      env {
        name  = "POLYMNEMO_API_KEYS"
        value = var.api_keys
      }

      # Media/blob env only when R2 is wired in (blob_backend = "s3"); absent
      # otherwise, so the app keeps the media tools off.
      dynamic "env" {
        for_each = var.blob_backend == "none" ? {} : {
          POLYMNEMO_BLOB_BACKEND           = var.blob_backend
          POLYMNEMO_BLOB_BUCKET            = var.blob_bucket
          POLYMNEMO_BLOB_ENDPOINT_URL      = var.blob_endpoint_url
          POLYMNEMO_BLOB_ACCESS_KEY_ID     = var.blob_access_key_id
          POLYMNEMO_BLOB_SECRET_ACCESS_KEY = var.blob_secret_access_key
        }
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

# --- Public access: anyone can reach the URL; polymnemo enforces bearer auth --
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.image == "" ? 0 : 1
  name     = google_cloud_run_v2_service.polymnemo[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
