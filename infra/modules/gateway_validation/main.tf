variable "pipeline_id" {
  description = "Pipeline ID to validate"
  type        = string
}

variable "timeout_minutes" {
  description = "Timeout in minutes for validation (minimum 15)"
  type        = number
  
  validation {
    condition     = var.timeout_minutes >= 15
    error_message = "Timeout must be at least 15 minutes."
  }
}

variable "check_interval_seconds" {
  description = "Check interval in seconds (minimum 5)"
  type        = number
  
  validation {
    condition     = var.check_interval_seconds >= 5
    error_message = "Check interval must be at least 5 seconds."
  }
}

variable "python_script_path" {
  description = "Path to the Python validation script"
  type        = string
  default     = "../tools/validate_running_gateway.py"
}

variable "yaml_config_path" {
  description = "Path to the YAML configuration file"
  type        = string
}

variable "ingestion_pipeline_ids" {
  description = "List of ingestion pipeline IDs to validate after gateway is running"
  type        = list(string)
  default     = []
}

# Run the gateway validation script
resource "null_resource" "gateway_validation" {
  triggers = {
    pipeline_id = var.pipeline_id
    timeout     = var.timeout_minutes
    interval    = var.check_interval_seconds
    config_hash = filemd5(var.yaml_config_path) # Hash of YAML config ensures idempotency - only triggers when config changes
  }
  
  # The Python program instantiates Databricks SDK Workspace client and relies on environment variables for authentication. E.g DATABRICKS_HOST and DATABRICKS_AUTH_TYPE
  provisioner "local-exec" {
    command = length(var.ingestion_pipeline_ids) > 0 ? "python ${var.python_script_path} --pipeline-id ${var.pipeline_id} --timeout ${var.timeout_minutes} --check-interval ${var.check_interval_seconds} --ingestion-pipeline-ids ${join(" ", var.ingestion_pipeline_ids)}" : "python ${var.python_script_path} --pipeline-id ${var.pipeline_id} --timeout ${var.timeout_minutes} --check-interval ${var.check_interval_seconds}"
  }
}

output "validation_completed" {
  description = "Indicates that gateway validation has completed successfully"
  value       = null_resource.gateway_validation.id
} 