# The test deployment's OWN media bucket, so an upload made against the test app
# never lands next to production media. The memory rows are already isolated by
# the Neon branch in test/; this closes the other half — blobs.
#
# Deliberately a separate root rather than a second bucket inside r2/: the roots
# are the isolation boundary here, and a test bucket that shares prod's state
# file can be destroyed by a bad plan against prod.
#
# Usage: same as r2/, with its own state key.
#   terraform init -backend-config=...key=r2-test.tfstate && terraform apply

module "r2" {
  source        = "../modules/r2"
  cf_account_id = var.cf_account_id
  bucket_name   = var.bucket_name
  location      = var.location
  token_name    = var.token_name

  access_key_id     = var.access_key_id
  secret_access_key = var.secret_access_key
}
