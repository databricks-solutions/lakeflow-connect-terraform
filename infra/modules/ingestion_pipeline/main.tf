variable "name" {
  description = "Name of the ingestion pipeline"
  type        = string
}

variable "destination_catalog" {
  description = "Name of the destination catalog where ingested tables will be created"
  type        = string
}

variable "destination_schema" {
  description = "Name of the destination schema within the destination catalog"
  type        = string
}

variable "source_catalog" {
  description = "Name of the source catalog , i.e. SQL database, from which to ingest tables"
  type        = string
}

variable "source_schema" {
  description = "Name of the source schema within the SQL database from which to ingest tables"
  type        = string
}

variable "gateway_pipeline_id" {
  description = "Gateway pipeline ID generated from upstream gateway module"
  type        = string
}

variable "source_type" {
  description = "Source type of the connection"
  type        = string
}

variable "specific_tables" {
  description = "List of specific tables to ingest instead of entire schema"
  type = list(object({
    source_table          = string
    destination_table     = optional(string) # Optional: if not provided, uses source_table
    destination_catalog   = optional(string)  # Optional: if not provided, uses pipeline-level destination_catalog
    destination_schema    = optional(string)  # Optional: if not provided, uses pipeline-level destination_schema
  }))
  default = []
}

variable "use_schema_ingestion" {
  description = "Whether to ingest entire schema or specific tables"
  type = bool
  default = true
}

variable "source_configurations" {
  description = "Source configurations for PostgreSQL (replication slot and publication)"
  type = object({
    source_catalog   = string
    publication_name = string
    slot_name        = string
  })
  default = null
}

variable "event_log_to_table" {
  description = "Whether to materialize event logs to Delta table for the ingestion pipeline"
  type        = bool
  default     = true
}

resource "databricks_pipeline" "ingest" {
  name = var.name
  ingestion_definition {
    source_type          = var.source_type
    ingestion_gateway_id = var.gateway_pipeline_id
    
    # Use schema ingestion when use_schema_ingestion is true
    dynamic "objects" {
      for_each = var.use_schema_ingestion ? [1] : []
      content {
        schema {
          source_catalog      = var.source_catalog
          source_schema       = var.source_schema
          destination_catalog = var.destination_catalog
          destination_schema  = var.destination_schema
        }
      }
    }
    
    # Use table-level ingestion for specific tables only when use_schema_ingestion is false
    dynamic "objects" {
      for_each = !var.use_schema_ingestion ? var.specific_tables : []
      content {
        table {
          source_catalog      = var.source_catalog
          source_schema       = var.source_schema
          source_table        = objects.value.source_table
          destination_catalog = coalesce(objects.value.destination_catalog, var.destination_catalog)
          destination_schema  = coalesce(objects.value.destination_schema, var.destination_schema)
          destination_table   = coalesce(objects.value.destination_table, objects.value.source_table)
        }
      }
    }
    
    # PostgreSQL-specific: source_configurations for replication slot and publication (Public Preview)
    # Only added when source_type is POSTGRESQL and source_configurations are provided
    dynamic "source_configurations" {
      for_each = var.source_type == "POSTGRESQL" && var.source_configurations != null ? [var.source_configurations] : []
      content {
        catalog {
          source_catalog = source_configurations.value.source_catalog
          postgres {
            slot_config {
              publication_name = source_configurations.value.publication_name
              slot_name        = source_configurations.value.slot_name
            }
          }
        }
      }
    }
  }
  schema  = var.destination_schema
  catalog = var.destination_catalog

  # Dynamically adjust based on choice made in configuration
  dynamic "event_log" {
    for_each = var.event_log_to_table ? [1] : []
    content {
      name = "event_log_${var.name}"
    }
  }

}


output "pipeline_id" {
  value = databricks_pipeline.ingest.id
} 