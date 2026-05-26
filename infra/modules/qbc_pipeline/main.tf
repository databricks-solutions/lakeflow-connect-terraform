variable "pipeline_name" {
  description = "Display name of the QBC pipeline"
  type        = string
}

variable "connection_name" {
  description = "Unity Catalog connection name for the source database (null for foreign catalog ingestion)"
  type        = string
  default     = null
}

variable "ingest_from_uc_foreign_catalog" {
  description = "Set true when ingesting from a UC foreign catalog instead of a connection"
  type        = bool
  default     = false
}

variable "pipeline_configuration" {
  description = "Pipeline-level Spark configuration key-value pairs"
  type        = map(string)
  default     = {}
}

variable "source_type" {
  description = "Source database type (null for serverless — inferred from UC connection)"
  type        = string
  default     = null
}

variable "destination_catalog" {
  description = "Default destination catalog in Unity Catalog"
  type        = string
}

variable "destination_schema" {
  description = "Nominal pipeline-level destination schema (overridden per table object)"
  type        = string
}

variable "tables" {
  description = "Flattened list of tables to ingest with resolved cursor/scd/deletion fields"
  type = list(object({
    source_catalog      = optional(string, null) # null for MySQL/MariaDB (no catalog level)
    source_schema       = string
    source_table        = string
    destination_catalog = string
    destination_schema  = string
    destination_table   = optional(string) # Optional: if not provided, uses source_table
    cursor_column       = string
    scd_type            = string
    deletion_condition  = optional(string, null)
    primary_keys        = optional(list(string), [])
  }))
}

variable "event_log_to_table" {
  description = "Whether to materialize event logs to Delta tables"
  type        = bool
  default     = true
}

resource "databricks_pipeline" "qbc" {
  name = var.pipeline_name

  catalog = var.destination_catalog
  schema  = var.destination_schema

  # Providing ability to pass `configuration` from the config file to the QBC pipeline, in case some features need to be included for special handling of types or generally for the connector
  configuration = length(var.pipeline_configuration) > 0 ? var.pipeline_configuration : null

  dynamic "event_log" {
    for_each = var.event_log_to_table ? [1] : []
    content {
      name = "event_log_${var.pipeline_name}"
    }
  }

  ingestion_definition {
    connection_name                = var.connection_name
    ingest_from_uc_foreign_catalog = var.ingest_from_uc_foreign_catalog ? true : null

    # null = serverless (Databricks infers source type from the UC connection).
    # Set explicitly only if required for your source/compute combination.
    source_type = var.source_type

    dynamic "objects" {
      for_each = var.tables
      content {
        table {
          source_catalog = objects.value.source_catalog
          source_schema  = objects.value.source_schema
          source_table   = objects.value.source_table

          destination_catalog = objects.value.destination_catalog
          destination_schema  = objects.value.destination_schema
          destination_table   = coalesce(objects.value.destination_table, objects.value.source_table)

          table_configuration {
            primary_keys = length(objects.value.primary_keys) > 0 ? objects.value.primary_keys : null
            scd_type     = objects.value.scd_type

            query_based_connector_config {
              cursor_columns = [objects.value.cursor_column]
              # Only set deletion_condition when explicitly provided
              deletion_condition = objects.value.deletion_condition
            }
          }
        }
      }
    }
  }
}

output "pipeline_id" {
  description = "QBC pipeline ID"
  value       = databricks_pipeline.qbc.id
}
