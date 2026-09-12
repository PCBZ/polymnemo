# A DEBUG test environment: a Neon BRANCH of the prod project (isolated,
# copy-on-write — inherits the prod schema so no schema.sql step) + a Container
# App running the same GHCR image with POLYMNEMO_LOG_LEVEL=DEBUG. Its stdout goes
# to the module's own Log Analytics workspace, so the #96 read-payload observe
# lines are queryable with KQL (see README.md) — that's how we measure the
# embedding read cost before/after #89 without touching prod.
#
# NOTE: this terraform has NOT been apply-tested. The branch DSN (local.test_dsn)
# is assembled from the provider's role/password/pooled-host; verify it on the
# first `terraform apply` (a bad DSN just means the test app can't connect).

data "terraform_remote_state" "neon" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.tfstate_resource_group
    storage_account_name = var.tfstate_storage_account
    container_name       = var.tfstate_container
    key                  = "neon.tfstate"
  }
}

locals {
  project_id = data.terraform_remote_state.neon.outputs.project_id
  role       = data.terraform_remote_state.neon.outputs.database_user
  db         = data.terraform_remote_state.neon.outputs.database_name
}

# --- Test branch off prod (copy-on-write; carries the prod schema) ------------
resource "neon_branch" "test" {
  project_id = local.project_id
  parent_id  = data.terraform_remote_state.neon.outputs.default_branch_id
  name       = var.branch_name
}

resource "neon_endpoint" "test" {
  project_id = local.project_id
  branch_id  = neon_branch.test.id
  type       = "read_write"
}

data "neon_branch_role_password" "test" {
  project_id = local.project_id
  branch_id  = neon_branch.test.id
  role_name  = local.role
}

# Read back the branch's pooled host after the endpoint exists.
data "neon_branch_endpoints" "test" {
  project_id = local.project_id
  branch_id  = neon_branch.test.id
  depends_on = [neon_endpoint.test]
}

locals {
  # Pooled host of the branch's read_write endpoint (PgBouncer), matching how the
  # app connects in prod.
  test_host_pooler = one([
    for e in data.neon_branch_endpoints.test.endpoints :
    e.host_pooling if e.type == "read_write"
  ])
  test_dsn = "postgresql://${local.role}:${data.neon_branch_role_password.test.password}@${local.test_host_pooler}/${local.db}?sslmode=require"
}

module "container_apps" {
  source              = "../modules/container-apps"
  resource_group_name = "${var.service_name}-rg"
  location            = var.location
  service_name        = var.service_name
  image               = var.image
  database_url        = local.test_dsn
  api_keys            = var.api_keys
  log_level           = "DEBUG" # land the #96 observe lines in Log Analytics
  # media/blob stays off (default) for the test env.
}
