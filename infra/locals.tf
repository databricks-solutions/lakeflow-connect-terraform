locals {
  cfg = yamldecode(file(var.yaml_config_path))

  # Read variables from YAML instead of Terraform variables
  env      = local.cfg.env
  app_name = local.cfg.app_name

  connection = local.cfg.connection
  job        = local.cfg.job

  # MySQL has no schema level (database = schema). Used to set source_catalog/source_schema and table naming.
  is_mysql = try(local.connection.source_type, "") == "MYSQL"

  # Event log configuration - defaults to true if not specified
  event_log_to_table = try(local.cfg.event_log.to_table, true)

  # Unity Catalog configuration with validation
  # global_uc_catalog is required - if not provided, set to null to force Terraform error
  global_uc_catalog = try(local.cfg.unity_catalog.global_uc_catalog, null)
  
  # staging_uc_catalog defaults to global_uc_catalog if not provided
  # If global_uc_catalog is also null, this will be null and cause an error
  staging_uc_catalog = try(
    local.cfg.unity_catalog.staging_uc_catalog,
    local.global_uc_catalog
  )

  # Staging schema name for gateway pipeline
  # Defaults to {app_name}_lf_staging if not provided
  staging_schema_name = try(
    local.cfg.unity_catalog.staging_schema,
    "${local.app_name}_lf_staging"
  )

  # Get list of all unique landing schemas (based on source schema names with prefix/suffix)
  landing_schemas = distinct([
    for pair in local.database_schema_pairs :
    pair.destination_schema
  ])

  # All (catalog, schema) landing targets including per-table overrides (destination_catalog, destination_schema)
  all_landing_targets = distinct(flatten([
    for pair in local.database_schema_pairs :
    length(pair.specific_tables) > 0 ? [
      for t in pair.specific_tables : {
        catalog = try(t.destination_catalog, pair.uc_catalog)
        schema  = try(t.destination_schema, pair.destination_schema)
      }
    ] : [
      { catalog = pair.uc_catalog, schema = pair.destination_schema }
    ]
  ]))

  # Map catalog name -> list of schemas for validation (includes per-table overrides)
  landing_catalogs_map = {
    for catalog in distinct([for t in local.all_landing_targets : t.catalog]) :
    catalog => distinct([for t in local.all_landing_targets : t.schema if t.catalog == catalog])
  }


  # Create database-schema pairs for ingestion pipelines
  database_schema_pairs = distinct(flatten([
    for db in local.cfg.databases : [
      for i, schema in db.schemas : {
        database_name        = db.name
        schema_name          = schema.name
        pair_key             = local.is_mysql ? "${db.name}_schema_${i}" : "${db.name}_${schema.name}"   # For MySQL, concept of schema does not exist, hence handling through arbitrary index
        use_schema_ingestion = try(schema.use_schema_ingestion, true)
        specific_tables      = try(schema.tables, [])
        # For PostgreSQL: Pass replication slot and publication info if present
        replication_slot = try(db.replication_slot, null)
        publication      = try(db.publication, null)
        # UC catalog and schema configuration for this database-schema pair
        uc_catalog = try(db.uc_catalog, local.global_uc_catalog)
        # Build destination schema name: {prefix}{source_schema_name}{suffix}
        # For MySQL (no schema level), use database name so one UC schema per MySQL database
        destination_schema = local.is_mysql ? join("", [
          try(db.schema_prefix, ""),
          db.name,
          try(db.schema_suffix, "")
        ]) : join("", [
          try(db.schema_prefix, ""),
          schema.name,
          try(db.schema_suffix, "")
        ])
      }
    ]
  ]))

  # Build source_configurations map for each database (for PostgreSQL Public Preview)
  # This creates a map: database_name -> source_configurations object
  database_source_configurations = {
    for db in local.cfg.databases :
    db.name => (
      # Only create source_configurations if both replication_slot and publication are provided
      try(db.replication_slot, null) != null && try(db.publication, null) != null ? {
        source_catalog   = db.name
        publication_name = db.publication
        slot_name        = db.replication_slot
      } : null
    )
  }

  # Parse per-database job schedules when common_job_for_all_pipelines is false
  # Create a map of database names to their schedule configurations
  per_database_schedules = try(local.cfg.job.per_database_schedules, [])
  
  # Create a flattened map: database_name -> schedule_config
  database_to_schedule = merge([
    for schedule_config in local.per_database_schedules : {
      for db_name in schedule_config.applies_to :
      db_name => {
        name     = schedule_config.name
        schedule = schedule_config.schedule
      }
    }
  ]...)

  # Group database-schema pairs by their schedule
  # This creates a map: schedule_name -> list of database-schema pair keys
  schedule_to_pipelines = local.job.common_job_for_all_pipelines ? {} : {
    for schedule_config in local.per_database_schedules :
    schedule_config.name => [
      for pair in local.database_schema_pairs :
      pair.pair_key if contains(schedule_config.applies_to, pair.database_name)
    ]
  }
} 