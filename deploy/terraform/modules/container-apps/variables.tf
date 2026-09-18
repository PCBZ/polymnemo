variable "resource_group_name" {
  type        = string
  description = "Resource group to create for polymnemo."
}

variable "location" {
  type        = string
  description = "Azure region, e.g. westus2."
}

variable "service_name" {
  type        = string
  description = "Container App name (and prefix for the environment / identity)."
}

variable "image" {
  type        = string
  description = "Full container image reference the app runs, e.g. ghcr.io/pcbz/polymnemo:v1.0.0. Must be publicly pullable (no registry credentials are configured)."
}

variable "revision_suffix" {
  type        = string
  default     = ""
  description = "Appended to the revision name; set it to a per-deploy unique value (e.g. the CI run id) to force a fresh rollout even when the image ref is unchanged. Empty = Azure auto-generates one."
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "Postgres pooled connection string (from the shared Neon), injected as POLYMNEMO_DATABASE_URL."
}

variable "api_keys" {
  type        = string
  sensitive   = true
  description = "Per-user keys \"key1:alice,key2:bob\", injected as POLYMNEMO_API_KEYS."
}

# GitHub OAuth (#83). Leave both blank to run bearer-key auth only; the app
# enables OAuth exactly when the id, the secret and a base URL are all present.
variable "oauth_client_id" {
  type        = string
  default     = ""
  description = "GitHub OAuth app client id, injected as POLYMNEMO_OAUTH_CLIENT_ID."
}

variable "oauth_client_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "GitHub OAuth app client secret, injected as POLYMNEMO_OAUTH_CLIENT_SECRET."
}

variable "oauth_allowed_redirect_uris" {
  type        = string
  default     = ""
  description = "Comma-separated extra client redirect-URI patterns. Added to the localhost-only default, never replacing it."
}

variable "log_format" {
  type        = string
  default     = "json"
  description = "Injected as POLYMNEMO_LOG_FORMAT. Defaults to json here, not to the app's own \"text\" default: the per-call log (#93) is only queryable in Log Analytics as JSON, and leaving it unset shipped the feature switched off."
}

variable "log_level" {
  type        = string
  default     = "INFO"
  description = "Root log level, injected as POLYMNEMO_LOG_LEVEL. Set DEBUG on a test env to land the #96 read-payload observe lines in Log Analytics."
}

# --- Media / blob storage (R2). "none" leaves the media tools off. ------------
variable "blob_backend" {
  type        = string
  default     = "none"
  description = "\"none\" (media off) or \"s3\" (R2). When \"s3\", the four blob_* below are injected."
}

variable "blob_bucket" {
  type        = string
  default     = ""
  description = "R2 bucket name, injected as POLYMNEMO_BLOB_BUCKET."
}

variable "blob_endpoint_url" {
  type        = string
  default     = ""
  description = "R2 S3 endpoint, injected as POLYMNEMO_BLOB_ENDPOINT_URL."
}

variable "blob_access_key_id" {
  type        = string
  default     = ""
  sensitive   = true
  description = "R2 S3 access key id, injected (as a secret) into POLYMNEMO_BLOB_ACCESS_KEY_ID."
}

variable "blob_secret_access_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "R2 S3 secret access key, injected (as a secret) into POLYMNEMO_BLOB_SECRET_ACCESS_KEY."
}

# Sized from measurement, not from the default. Over 24h of production the
# container peaked at 137 MB of its 2Gi (6%) and 0.402 of its 1 vCPU (40%),
# averaging 0.007 vCPU — the app is idle almost always and bursty when it is
# not, because the only real work is an embedding.
#
# Halving both halves the bill: Container Apps charges per vCPU-second and
# GiB-second of active time, and the app is active ~86% of the day whatever
# the traffic (crawlers keep it awake — see the cost analysis in #146).
#
# 0.5 leaves the CPU peak at ~80% of quota, which is deliberate: that peak is
# the ONNX model initialising on a cold start, and it degrades by getting
# slower rather than by failing. 0.25 would put it at 160% and throttle.
variable "cpu" {
  type        = number
  default     = 0.5
  description = "vCPU per replica. Container Apps fixes cpu:memory at 1:2 (0.5 -> 1Gi)."
}

variable "memory" {
  type        = string
  default     = "1Gi"
  description = "Memory per replica; must match the cpu:memory 1:2 ratio."
}

variable "min_replicas" {
  type        = number
  default     = 0
  description = "0 = scale to zero when idle."
}

# How long a replica stays alive after its last request — and therefore how
# long it is billed for. The default is 300s, which is the single largest cost
# driver here: the app is probed by MCP directory crawlers every ~35s (median),
# so at 300s every probe buys five minutes and the replica never sleeps.
#
# Measured over 24h of real traffic (847 requests), active time by cooldown:
#   300s -> 20.7h/day   120s -> 12.6h/day   60s -> 7.3h/day   30s -> 4.0h/day
#
# The saving does not come from shorter tails — those roughly cancel against
# the larger number of clusters. It comes from the 185 gaps that fall between
# 120s and 300s: at 300s those are *inside* a billed window, at 60s they are
# sleep. 30s buys little more while adding cold starts, which cost ~4s each.
variable "cooldown_seconds" {
  type        = number
  default     = 60
  description = "Seconds a replica stays warm after its last request. Billed time."
}

variable "max_replicas" {
  type        = number
  default     = 3
  description = "Max replicas under load."
}

# --- Attaching to an existing platform ---------------------------------------
# Set both together to put this app next to one that already exists, rather than
# creating a resource group / workspace / environment of its own. The test app
# does this because the subscription allows one managed environment per region.
# Leave them empty (the default) to create the platform.
#
# Names, not ids: a name is a deterministic string the caller already knows,
# while an id has to come from the other root's state and therefore only exists
# after that root has applied.
variable "existing_environment_name" {
  description = "Container App Environment to attach to. Empty creates one."
  type        = string
  default     = ""
}

variable "existing_log_workspace_name" {
  description = "Name of the Log Analytics workspace that environment logs to."
  type        = string
  default     = ""
}
