# polymnemo on Azure Container Apps: resource group, ACR, a pull identity, the
# managed environment, and the app itself. The DB URL + API keys arrive as inputs
# (the shared Neon URL comes from the neon root) and are injected as app secrets.

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}

# --- Container registry (az acr build pushes the image here) -----------------
resource "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false
}

# --- Least-privilege identity the app uses to pull from ACR ------------------
resource "azurerm_user_assigned_identity" "pull" {
  name                = "${var.service_name}-acr-pull"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.pull.principal_id
}

# Azure RBAC is eventually consistent (assignment takes tens of seconds to
# propagate). Without this wait, a one-shot apply can hit "UNAUTHORIZED" on the
# first image pull. time_sleep delays the app until the grant is effective.
resource "time_sleep" "acr_rbac_propagation" {
  depends_on      = [azurerm_role_assignment.acr_pull]
  create_duration = "60s"
}

# --- Log Analytics: persistent destination for container logs ---------------
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.service_name}-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# --- Managed environment (Consumption plan; scale-to-zero capable) -----------
resource "azurerm_container_app_environment" "this" {
  name                       = "${var.service_name}-env"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
}

# --- The app (skipped on the bootstrap apply, when image == "") --------------
resource "azurerm_container_app" "this" {
  count                        = var.image == "" ? 0 : 1
  name                         = var.service_name
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pull.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.pull.id
  }

  # Secrets stay out of the plain env; injected via secret_name below.
  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "api-keys"
    value = var.api_keys
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
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

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
        name        = "POLYMNEMO_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "POLYMNEMO_API_KEYS"
        secret_name = "api-keys"
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

  depends_on = [time_sleep.acr_rbac_propagation]
}
