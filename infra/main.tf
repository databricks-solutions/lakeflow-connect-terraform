# Validate the current Databricks user being used for authentication for the project
data "databricks_current_user" "me" {}


# Validate staging catalog and schema for gateway pipeline
module "staging" {
  source = "./modules/validate_catalog_and_schemas"

  catalog_name = local.staging_uc_catalog
  schemas      = [local.staging_schema_name]
}

# Validate catalogs and schemas where ingestion pipelines will land data
# Group schemas by their target catalog
module "landing_catalog_validation" {
  source   = "./modules/validate_catalog_and_schemas"
  for_each = local.landing_catalogs_map

  catalog_name = each.key
  schemas = distinct([
    for pair in local.database_schema_pairs :
    pair.destination_schema
    if pair.uc_catalog == each.key
  ])
}

module "gateway" {
  source = "./modules/gateway_pipeline"

  name                    = "lf-connect-${local.app_name}-gateway"
  connection_name         = local.connection.name
  gateway_storage_catalog = local.staging_uc_catalog
  gateway_storage_schema  = local.staging_schema_name
  source_type             = try(local.connection.source_type, null)
  connection_parameters  = try(local.connection.connection_parameters, null)
  cluster                 = local.cfg.gateway_pipeline_cluster_config
  cluster_policy_name     = local.cfg.gateway_pipeline_cluster_policy_name
  event_log_to_table      = local.event_log_to_table
  depends_on              = [module.staging]
}

module "ingestion" {
  source = "./modules/ingestion_pipeline"

  for_each = { for pair in local.database_schema_pairs : pair.pair_key => pair }

  name                  = "${each.value.database_name}-${each.value.schema_name}-ingestion"
  source_catalog        = each.value.database_name
  source_schema         = each.value.schema_name
  destination_catalog   = each.value.uc_catalog
  destination_schema    = each.value.destination_schema
  gateway_pipeline_id   = module.gateway.pipeline_id
  source_type           = local.connection.source_type
  use_schema_ingestion  = each.value.use_schema_ingestion
  specific_tables       = each.value.specific_tables
  source_configurations = lookup(local.database_source_configurations, each.value.database_name, null)
  event_log_to_table    = local.event_log_to_table

  depends_on = [module.gateway, module.landing_catalog_validation]
}

# Validate that the gateway pipeline is running before proceeding to orchestrator
module "gateway_validation" {
  source = "./modules/gateway_validation"

  pipeline_id            = module.gateway.pipeline_id
  timeout_minutes        = local.cfg.gateway_validation.timeout_minutes
  check_interval_seconds = local.cfg.gateway_validation.check_interval_seconds
  yaml_config_path       = var.yaml_config_path
  ingestion_pipeline_ids = [for k, v in module.ingestion : v.pipeline_id]

  depends_on = [module.gateway, module.ingestion]
}

module "orchestrator_shared_all_pipelines" {
  source = "./modules/job"

  count = local.job.common_job_for_all_pipelines ? 1 : 0

  name                = "lf-connect-${local.app_name}-common-job"
  ingestion_pipelines = { for k, v in module.ingestion : k => v.pipeline_id }
  schedule            = local.job.common_schedule
  is_common_job       = true

  depends_on = [module.gateway_validation]
}

# Create individual jobs per schedule group when common_job_for_all_pipelines is false
module "orchestrator_per_schedule" {
  source = "./modules/job"

  for_each = local.job.common_job_for_all_pipelines ? {} : local.schedule_to_pipelines

  name = "lf-connect-${local.app_name}-${each.key}"
  ingestion_pipelines = {
    for pair_key in each.value :
    pair_key => module.ingestion[pair_key].pipeline_id
  }
  schedule = lookup(
    [for s in local.per_database_schedules : s if s.name == each.key][0],
    "schedule"
  )
  is_common_job = false

  depends_on = [module.gateway_validation]
}

