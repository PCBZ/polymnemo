# polymnemo as a Cloud Run service: the run API, a least-privilege runtime
# service account, the service itself, and public access. The image is the SAME
# public GHCR image Azure runs (var.image, e.g. ghcr.io/pcbz/polymnemo:v1.0.0) —
# Cloud Run can pull a public ghcr.io image directly, so there's no Artifact
# Registry or Cloud Build here. The DB URL + API keys arrive as inputs (from the
# neon/r2 roots) and are injected as env.

resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "iam.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Least-privilege runtime service account --------------------------------
resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "polymnemo Cloud Run runtime"
  depends_on   = [google_project_service.services]
}

# --- Cloud Run service (runs the public GHCR image directly) -----------------
resource "google_cloud_run_v2_service" "polymnemo" {
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
  name     = google_cloud_run_v2_service.polymnemo.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
