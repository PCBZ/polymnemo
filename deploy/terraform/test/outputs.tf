output "database_url" {
  description = "Pooled DSN for the test branch — export as POLYMNEMO_DATABASE_URL."
  value       = local.test_dsn
  sensitive   = true
}

output "branch_id" {
  description = "Neon branch id (handy for the Neon console / CLI)."
  value       = neon_branch.test.id
}
