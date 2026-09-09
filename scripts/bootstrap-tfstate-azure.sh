#!/usr/bin/env bash
#
# One-time bootstrap: create the Azure Storage that holds Terraform state for the
# CI deploy, and publish its coordinates as GitHub Actions variables so the
# deploy workflow can `terraform init` against it.
#
#   az login                              # a principal that can create resources
#   bash scripts/bootstrap-tfstate-azure.sh
#
# Override any name via env, e.g. LOCATION=eastus bash scripts/bootstrap-...sh
# Re-running is safe: az creates are idempotent and gh variable set overwrites.

set -euo pipefail

LOCATION="${LOCATION:-westus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-polymnemo-tfstate-rg}"
CONTAINER="${CONTAINER:-tfstate}"
# Storage account names are global + 3-24 lowercase alphanumeric.
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-polymnemotfstate$RANDOM}"

command -v az >/dev/null || { echo "error: az CLI not installed." >&2; exit 1; }
command -v gh >/dev/null || { echo "error: gh CLI not installed." >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "error: run 'az login' first." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: run 'gh auth login' first." >&2; exit 1; }

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
echo "The CI service principal (ARM_CLIENT_ID) must be able to reach this account —"
echo "'Contributor' on the subscription (from az ad sp create-for-rbac) covers it,"
echo "since the azurerm backend fetches the storage key via ARM."
echo "Next: run the 'deploy (azure)' workflow (Actions tab -> Run workflow)."
