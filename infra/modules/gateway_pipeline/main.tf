

variable "name" {
  description = "Name of the Gateway pipeline"
  type        = string
}

variable "connection_name" {
  description = "Name of the UC Connection used. Needs to match exactly"
  type        = string
}

variable "gateway_storage_catalog" {
  description = "Catalog where the staging schemas will be placed"
  type        = string
}

variable "gateway_storage_schema" {
  description = "Name of the staging schema for the application"
  type        = string
}

variable "source_type" {
  description = "Source type of the connection (e.g. SQLSERVER, POSTGRESQL, ORACLE). When ORACLE, connection_parameters may be set."
  type        = string
  default     = null
}

variable "connection_parameters" {
  description = "Optional connection parameters for the gateway. Only used when source_type is ORACLE (e.g. source_catalog for Oracle CDB)."
  type = object({
    source_catalog = optional(string)
  })
  default = null
}

variable "cluster" {
  description = "Cluster configuration for the gateway pipeline"
  type = object({
    label                        = string
    node_type_id                 = string
    driver_node_type_id          = optional(string)
    num_workers                  = optional(number)
    autoscale = optional(object({
      min_workers = number
      max_workers = number
      mode        = string
    }))
    apply_policy_default_values  = bool
    enable_local_disk_encryption = bool
    custom_tags                  = map(string)
    spark_conf                   = map(string)
    spark_env_vars               = map(string)
    ssh_public_keys              = list(string)
  })
}

variable "cluster_policy_name" {
  description = "Name of the cluster policy to use for the gateway pipeline cluster"
  type        = string
  
}

variable "event_log_to_table" {
  description = "Whether to materialize event logs to Delta table for the gateway pipeline"
  type        = bool
  default     = true
}

# Gather the existing cluster policy using name
data "databricks_cluster_policy" "app_cluster_policy" {
  name = var.cluster_policy_name
}

# Create single gateway pipeline (i.e. only one for the connection to the SQL Database server)
resource "databricks_pipeline" "gateway" {

  name = var.name
  gateway_definition {
    connection_name         = var.connection_name
    gateway_storage_catalog = var.gateway_storage_catalog
    gateway_storage_schema  = var.gateway_storage_schema
    gateway_storage_name    = "staging_folder"

    # connection_parameters only when source_type is ORACLE (e.g. source_catalog for CDB).
    # source_type is not an attribute on gateway_definition in the Terraform provider.
    dynamic "connection_parameters" {
      for_each = var.source_type == "ORACLE" && var.connection_parameters != null ? [1] : []
      content {
        source_catalog = try(var.connection_parameters.source_catalog, null)
      }
    }
  }
  allow_duplicate_names  = false
  development            = false
  continuous             = true
  serverless             = false
  expected_last_modified = 0
  schema                 = var.gateway_storage_schema
  catalog                = var.gateway_storage_catalog

  cluster {
    label                        = var.cluster.label
    node_type_id                 = var.cluster.node_type_id
    policy_id                   = data.databricks_cluster_policy.app_cluster_policy.id
    #driver_node_type_id          = var.cluster.driver_node_type_id
    #num_workers                  = var.cluster.num_workers
    apply_policy_default_values  = var.cluster.apply_policy_default_values
    enable_local_disk_encryption = var.cluster.enable_local_disk_encryption
    custom_tags                  = var.cluster.custom_tags
    spark_conf                   = var.cluster.spark_conf
    spark_env_vars               = var.cluster.spark_env_vars
    ssh_public_keys              = var.cluster.ssh_public_keys
    
    autoscale {
      min_workers = var.cluster.autoscale.min_workers
      max_workers = var.cluster.autoscale.max_workers
      mode        = var.cluster.autoscale.mode
    }
  }

  # Dynamically write to event log table based on choice made in configuration
  dynamic "event_log" {
    for_each = var.event_log_to_table ? [1] : []
    content {
      name = "event_log_${var.name}"
    }
  }

}

output "pipeline_id" {
  value = databricks_pipeline.gateway.id
} 