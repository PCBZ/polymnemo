# A Neon BRANCH of the prod project — isolated and copy-on-write, so it inherits
# the prod schema AND data (no schema.sql step) while keeping the measurement's
# writes off prod. That's the whole test env: point a locally-run polymnemo at
# `database_url` with POLYMNEMO_LOG_LEVEL=DEBUG and the #96 observe lines land in
# your terminal. See README.md.

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

locals {
  # host_pooling is the PgBouncer host, matching how prod connects.
  test_dsn = "postgresql://${local.role}:${data.neon_branch_role_password.test.password}@${neon_endpoint.test.host_pooling}/${local.db}?sslmode=require"
}
