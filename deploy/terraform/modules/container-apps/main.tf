# polymnemo on Azure Container Apps: resource group, Log Analytics, a managed
# environment, and the app. The image is built + pushed to GHCR by the deploy
# workflow and pulled here by full reference (var.image) — Azure runs the
# container only. (ACR Tasks are blocked on personal/student subscriptions, and
# the SP can't create the AcrPull role assignment, so we host the image on GHCR
# instead — public, so the app needs no registry credentials.) The DB URL + API
# keys arrive as inputs (the shared Neon URL comes from the neon root) and are
# injected as app secrets.

# --- Platform: created once, then shared -------------------------------------
# The subscription allows ONE managed environment per region (measured: westus2
# reports "Managed Environment Count 1/1"), so a second app in the same region
# cannot bring its own. Naming an existing environment attaches to it; leaving
# it empty creates the whole platform, which is what the prod root does. Cores
# are the quota that actually matters for a second app, and those are 1/100.
#
# Attaching keys off NAMES and resolves everything else through data sources —
# never an id threaded in from another root's outputs. Those outputs only exist
# once that root has applied, which deadlocks any pipeline that deploys the
# attached app first.
locals {
  create_platform = var.existing_environment_name == ""
}

resource "azurerm_resource_group" "this" {
  count    = local.create_platform ? 1 : 0
  name     = var.resource_group_name
  location = var.location
}

data "azurerm_resource_group" "existing" {
  count = local.create_platform ? 0 : 1
  name  = var.resource_group_name
}

# --- Log Analytics: persistent destination for container logs ---------------
resource "azurerm_log_analytics_workspace" "this" {
  count               = local.create_platform ? 1 : 0
  name                = "${var.service_name}-logs"
  resource_group_name = local.resource_group_name
  location            = local.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

data "azurerm_log_analytics_workspace" "existing" {
  count               = local.create_platform ? 0 : 1
  name                = var.existing_log_workspace_name
  resource_group_name = var.resource_group_name
}

# --- Managed environment (Consumption plan; scale-to-zero capable) -----------
resource "azurerm_container_app_environment" "this" {
  count                      = local.create_platform ? 1 : 0
  name                       = "${var.service_name}-env"
  resource_group_name        = local.resource_group_name
  location                   = local.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this[0].id
}

# Every reference below goes through these, so the created and attached cases
# read identically from here on.
locals {
  resource_group_name = (local.create_platform
    ? azurerm_resource_group.this[0].name
  : data.azurerm_resource_group.existing[0].name)
  location = (local.create_platform
    ? azurerm_resource_group.this[0].location
  : data.azurerm_resource_group.existing[0].location)
  environment_id = (local.create_platform
    ? azurerm_container_app_environment.this[0].id
  : data.azurerm_container_app_environment.existing[0].id)
  environment_default_domain = (local.create_platform
    ? azurerm_container_app_environment.this[0].default_domain
  : data.azurerm_container_app_environment.existing[0].default_domain)
  log_workspace_id = (local.create_platform
    ? azurerm_log_analytics_workspace.this[0].workspace_id
  : data.azurerm_log_analytics_workspace.existing[0].workspace_id)
}

data "azurerm_container_app_environment" "existing" {
  count               = local.create_platform ? 0 : 1
  name                = var.existing_environment_name
  resource_group_name = var.resource_group_name
}

# Keep prod's state addresses valid across the `count` added above: without
# these, `terraform apply` would destroy and recreate the environment, the
# workspace and the resource group holding the live service.
moved {
  from = azurerm_resource_group.this
  to   = azurerm_resource_group.this[0]
}

moved {
  from = azurerm_log_analytics_workspace.this
  to   = azurerm_log_analytics_workspace.this[0]
}

moved {
  from = azurerm_container_app_environment.this
  to   = azurerm_container_app_environment.this[0]
}

# Pulls a PUBLIC image from GHCR, so no `identity` / `registry` credentials are
# needed.
resource "azurerm_container_app" "this" {
  name                         = var.service_name
  resource_group_name          = local.resource_group_name
  container_app_environment_id = local.environment_id
  revision_mode                = "Single"

  # Secrets stay out of the plain env; injected via secret_name below.
  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "api-keys"
    value = var.api_keys
  }

  # OAuth client secret, only when OAuth is configured. A Container App secret
  # cannot hold an empty value, so this block has to disappear rather than pass "".
  dynamic "secret" {
    for_each = var.oauth_client_id == "" ? {} : {
      "oauth-client-secret" = var.oauth_client_secret
    }
    content {
      name  = secret.key
      value = secret.value
    }
  }

  # R2 S3 credentials as secrets (only when media is enabled).
  dynamic "secret" {
    for_each = var.blob_backend == "none" ? {} : {
      "blob-access-key-id"     = var.blob_access_key_id
      "blob-secret-access-key" = var.blob_secret_access_key
    }
    content {
      name  = secret.key
      value = secret.value
    }
  }

  # Public HTTPS ingress; polymnemo enforces its own bearer auth.
  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas               = var.min_replicas
    max_replicas               = var.max_replicas
    cooldown_period_in_seconds = var.cooldown_seconds

    # A changing suffix forces a new revision each deploy (so a re-run actually
    # rolls out); empty lets Azure auto-generate one.
    revision_suffix = var.revision_suffix != "" ? var.revision_suffix : null

    container {
      name   = var.service_name
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      # Container Apps doesn't inject PORT (unlike Cloud Run); pin it to the
      # image's exposed port so the app binds where ingress routes.
      env {
        name  = "PORT"
        value = "8080"
      }
      env {
        name  = "POLYMNEMO_LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "POLYMNEMO_LOG_FORMAT"
        value = var.log_format
      }
      env {
        name        = "POLYMNEMO_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "POLYMNEMO_API_KEYS"
        secret_name = "api-keys"
      }

      # OAuth env, matched to the secret above. The base URL is this app's own
      # public origin, so the callback lands back here at /auth/callback — built
      # from the ENVIRONMENT's default domain, not from this resource's own
      # ingress.fqdn, which would be a self-reference and a dependency cycle.
      dynamic "env" {
        for_each = var.oauth_client_id == "" ? {} : {
          POLYMNEMO_OAUTH_CLIENT_ID             = var.oauth_client_id
          POLYMNEMO_OAUTH_ALLOWED_REDIRECT_URIS = var.oauth_allowed_redirect_uris
          POLYMNEMO_OAUTH_BASE_URL = join("", [
            "https://", var.service_name, ".",
            local.environment_default_domain,
          ])
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.oauth_client_id == "" ? {} : {
          POLYMNEMO_OAUTH_CLIENT_SECRET = "oauth-client-secret"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      # Media/blob env only when R2 is wired in. Non-secret settings as plain
      # env; the two credentials via the secrets declared above.
      dynamic "env" {
        for_each = var.blob_backend == "none" ? {} : {
          POLYMNEMO_BLOB_BACKEND      = var.blob_backend
          POLYMNEMO_BLOB_BUCKET       = var.blob_bucket
          POLYMNEMO_BLOB_ENDPOINT_URL = var.blob_endpoint_url
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.blob_backend == "none" ? {} : {
          POLYMNEMO_BLOB_ACCESS_KEY_ID     = "blob-access-key-id"
          POLYMNEMO_BLOB_SECRET_ACCESS_KEY = "blob-secret-access-key"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}
