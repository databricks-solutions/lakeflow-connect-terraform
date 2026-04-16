output "current_user" {
  value = data.databricks_current_user.me.user_name
}

# output "connection_id" {
#   description = "ID of Unity Catalog SQL Server connection"
#   value       = module.connection.connection_id
# }

output "landing_catalogs" {
  description = "Landing catalogs validated for ingestion pipelines"
  value       = { for k, v in module.landing_catalog_validation : k => v.catalog_name }
}

output "landing_schemas_by_catalog" {
  description = "Landing schemas grouped by catalog"
  value = {
    for catalog_name, catalog_module in module.landing_catalog_validation :
    catalog_name => distinct([
      for pair in local.database_schema_pairs :
      pair.destination_schema
      if pair.uc_catalog == catalog_name
    ])
  }
}


# ── CDC-only outputs ──────────────────────────────────────────────────────────

output "staging_catalog" {
  description = "Staging catalog for gateway pipeline (CDC only)"
  value       = length(module.staging) > 0 ? module.staging[0].catalog_name : null
}

output "gateway_pipeline_id" {
  description = "Gateway pipeline ID (CDC only)"
  value       = length(module.gateway) > 0 ? module.gateway[0].pipeline_id : null
}

output "ingestion_pipeline_id_map" {
  description = "Ingestion pipeline IDs mapped by pipeline name (CDC only)"
  value       = { for k, v in module.ingestion : k => v.pipeline_id }
}

output "common_orchestrator_all_pipelines" {
  description = "Key value pair of job name and ID (CDC only)"
  value       = length(module.orchestrator_shared_all_pipelines) > 0 ? module.orchestrator_shared_all_pipelines[0].common_orchestrator_all_pipelines : {}
}


# ── QBC-only outputs ──────────────────────────────────────────────────────────

output "qbc_pipeline_id" {
  description = "QBC pipeline ID (QBC only)"
  value       = length(module.qbc) > 0 ? module.qbc[0].pipeline_id : null
}
