# Validate the current Databricks user being used for authentication for the project
data "databricks_current_user" "me" {}


# ── Shared: validate destination catalogs and schemas for both CDC and QBC ────

# Validate catalogs and schemas where data will land (includes per-table overrides).
# Runs for both CDC and QBC — landing_catalogs_map is populated from database_schema_pairs
# which is derived from cfg.databases regardless of connector_type.
module "landing_catalog_validation" {
  source   = "./modules/validate_catalog_and_schemas"
  for_each = local.landing_catalogs_map

  catalog_name = each.key
  schemas      = each.value
}


# ── CDC-only resources ────────────────────────────────────────────────────────

# Validate staging catalog and schema for gateway pipeline (CDC only)
module "staging" {
  source = "./modules/validate_catalog_and_schemas"
  count  = local.is_cdc ? 1 : 0

  catalog_name = local.staging_uc_catalog
  schemas      = [local.staging_schema_name]
}

module "gateway" {
  source = "./modules/gateway_pipeline"
  count  = local.is_cdc ? 1 : 0

  name                    = "lf-connect-${local.app_name}-gateway"
  connection_name         = local.connection.name
  gateway_storage_catalog = local.staging_uc_catalog
  gateway_storage_schema  = local.staging_schema_name
  source_type             = try(local.connection.source_type, null)
  connection_parameters   = try(local.connection.connection_parameters, null)
  cluster                 = local.cfg.gateway_pipeline_cluster_config
  cluster_policy_name     = local.cfg.gateway_pipeline_cluster_policy_name
  event_log_to_table      = local.event_log_to_table
  depends_on              = [module.staging]
}

module "ingestion" {
  source = "./modules/ingestion_pipeline"

  for_each = local.is_cdc ? { for pair in local.database_schema_pairs : pair.pair_key => pair } : {}

  name                  = local.is_mysql ? "${each.value.pair_key}-ingestion" : "${each.value.database_name}-${each.value.schema_name}-ingestion"
  source_catalog        = local.is_mysql ? "default_catalog" : each.value.database_name
  source_schema         = local.is_mysql ? each.value.database_name : each.value.schema_name
  destination_catalog   = each.value.uc_catalog
  destination_schema    = each.value.destination_schema
  gateway_pipeline_id   = module.gateway[0].pipeline_id
  source_type           = local.connection.source_type
  use_schema_ingestion  = local.is_mysql ? false : each.value.use_schema_ingestion
  specific_tables       = each.value.specific_tables
  source_configurations = lookup(local.database_source_configurations, each.value.database_name, null)
  event_log_to_table    = local.event_log_to_table

  depends_on = [module.gateway, module.landing_catalog_validation]
}

# Validate that the gateway pipeline is running before proceeding to orchestrator.
# Set gateway_validation.enabled: false in the YAML config to skip this step
# (useful when pipelines are already running and a validate-only run would fail).
module "gateway_validation" {
  source = "./modules/gateway_validation"
  count  = (local.is_cdc && local.gateway_validation_enabled) ? 1 : 0

  pipeline_id            = module.gateway[0].pipeline_id
  timeout_minutes        = try(local.cfg.gateway_validation.timeout_minutes, 30)
  check_interval_seconds = try(local.cfg.gateway_validation.check_interval_seconds, 15)
  yaml_config_path       = var.yaml_config_path
  ingestion_pipeline_ids = [for k, v in module.ingestion : v.pipeline_id]

  depends_on = [module.gateway, module.ingestion]
}

module "orchestrator_shared_all_pipelines" {
  source = "./modules/job"

  count = (local.is_cdc && local.job.common_job_for_all_pipelines) ? 1 : 0

  name                = "lf-connect-${local.app_name}-common-job"
  ingestion_pipelines = { for k, v in module.ingestion : k => v.pipeline_id }
  schedule            = local.job.common_schedule
  is_common_job       = true

  depends_on = [module.gateway_validation]
}

# Create individual jobs per schedule group when common_job_for_all_pipelines is false
module "orchestrator_per_schedule" {
  source = "./modules/job"

  for_each = (local.is_cdc && !local.job.common_job_for_all_pipelines) ? local.schedule_to_pipelines : {}

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


# ── QBC-only resources ────────────────────────────────────────────────────────

# Single managed ingestion pipeline for all QBC sources.
# Uses serverless compute — no gateway pipeline or cluster config required.
module "qbc" {
  source = "./modules/qbc_pipeline"
  count  = local.is_qbc ? 1 : 0

  pipeline_name       = "lf-connect-${local.app_name}-qbc"
  connection_name     = local.connection.name
  source_type         = null # serverless — inferred from UC connection
  # Pipeline-level catalog/schema is required by Databricks even when each table
  # specifies its own destination. Fall back to the first table's catalog when
  # global_uc_catalog is null (i.e. per-database uc_catalog overrides are in use).
  destination_catalog = coalesce(local.global_uc_catalog, local.qbc_tables[0].destination_catalog)
  destination_schema  = local.qbc_tables[0].destination_schema
  tables              = local.qbc_tables
  event_log_to_table  = local.event_log_to_table

  depends_on = [module.landing_catalog_validation]
}

# Orchestration job for the QBC pipeline — uses common_schedule.
module "orchestrator_qbc" {
  source = "./modules/job"
  count  = local.is_qbc ? 1 : 0

  name                = "lf-connect-${local.app_name}-qbc-job"
  ingestion_pipelines = { "qbc" = module.qbc[0].pipeline_id }
  schedule            = local.job.common_schedule
  is_common_job       = true

  depends_on = [module.qbc]
}
