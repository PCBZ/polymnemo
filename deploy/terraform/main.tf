module "neon" {
  source     = "./modules/neon"
  name       = var.service_name
  region_id  = var.neon_region_id
  pg_version = 16
}

module "cloud_run" {
  source       = "./modules/cloud-run"
  project_id   = var.project_id
  region       = var.region
  service_name = var.service_name
  image        = var.image
  database_url = module.neon.connection_uri_pooler
  api_keys     = var.api_keys
  # memory / cpu / max_instances / concurrency use the module defaults.
}
