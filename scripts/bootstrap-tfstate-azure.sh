#!/usr/bin/env bash
#
# One-time bootstrap: create the Azure Storage that holds Terraform state for the
# CI deploy, and publish its coordinates as GitHub Actions variables so the
# deploy workflow can `terraform init` against it.
#
# Deliberately a plain script, not a Terraform root: this creates the very store
# that every root uses for its state, so it can't keep its own state there
# (chicken-and-egg). An imperative script has no state to keep — the standard
# approach (HashiCorp's own azurerm backend tutorial bootstraps with the CLI too).
#
#   az login                              # a principal that can create resources
#   bash scripts/bootstrap-tfstate-azure.sh
#
# Override any name via env, e.g. LOCATION=eastus bash scripts/bootstrap-...sh
# Re-running is safe: the storage account name is stable (reused / deterministic),
# az creates are idempotent, and gh variable set overwrites.

set -euo pipefail

LOCATION="${LOCATION:-westus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-polymnemo-tfstate-rg}"
CONTAINER="${CONTAINER:-tfstate}"

command -v az >/dev/null || { echo "error: az CLI not installed." >&2; exit 1; }
command -v gh >/dev/null || { echo "error: gh CLI not installed." >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "error: run 'az login' first." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: run 'gh auth login' first." >&2; exit 1; }

# Pick the storage-account name once and STABLY so re-running reuses the same
# state store instead of orphaning it: an explicit override, else the name
# already recorded in the repo variable, else a deterministic name derived from
# the subscription id (globally unique; 3-24 lowercase alphanumeric).
existing_sa="$(gh variable get TFSTATE_STORAGE_ACCOUNT 2>/dev/null || true)"
det_sa="polymnemotf$(az account show --query id -o tsv | tr -d '-' | cut -c1-13)"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-${existing_sa:-$det_sa}}"

echo "Resource group : $RESOURCE_GROUP ($LOCATION)"
echo "Storage account: $STORAGE_ACCOUNT"
echo "Container      : $CONTAINER"
echo

az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none
az storage account create \
  --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none

# Create the state container using the account key (avoids RBAC data-plane lag).
key="$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
  --query '[0].value' -o tsv)"
az storage container create \
  --name "$CONTAINER" --account-name "$STORAGE_ACCOUNT" --account-key "$key" -o none

# Publish coordinates so the deploy workflow can init the backend.
gh variable set TFSTATE_RESOURCE_GROUP  --body "$RESOURCE_GROUP"
gh variable set TFSTATE_STORAGE_ACCOUNT --body "$STORAGE_ACCOUNT"
gh variable set TFSTATE_CONTAINER       --body "$CONTAINER"

echo
echo "Done. GitHub variables set: TFSTATE_RESOURCE_GROUP / _STORAGE_ACCOUNT / _CONTAINER."
echo
echo "IMPORTANT: do NOT delete $RESOURCE_GROUP / $STORAGE_ACCOUNT by hand. It holds"
echo "every root's Terraform state and is intentionally NOT managed by Terraform (so"
echo "it can't be recreated by an apply). Deleting it orphans all deployed infra."
echo
echo "The CI service principal (ARM_CLIENT_ID) must be able to reach this account —"
echo "'Contributor' on the subscription (from az ad sp create-for-rbac) covers it,"
echo "since the azurerm backend fetches the storage key via ARM."
echo "Next: run the 'deploy (azure)' workflow (Actions tab -> Run workflow)."
