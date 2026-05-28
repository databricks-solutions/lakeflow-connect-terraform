variable "name" {
  type = string
}

variable "ingestion_pipelines" {
  description = "Map of ingestion pipeline names to pipeline IDs"
  type        = map(string)
}

variable "schedule" {
  description = "Schedule configuration for the job"
  type = object({
    quartz_cron_expression = string
    timezone_id            = string
  })
}

variable "is_common_job" {
  description = "Whether this is a common job for all pipelines or an individual job"
  type        = bool
}

variable "permissions" {
  description = "List of permission grants for this job"
  type = list(object({
    level                  = string
    user_name              = optional(string)
    group_name             = optional(string)
    service_principal_name = optional(string)
  }))
  default = []
}

# Create one job with all pipelines in it (for common job scenario)
resource "databricks_job" "common_orchestrator_all_pipelines" {
  count = var.is_common_job ? 1 : 0

  name                = var.name
  max_concurrent_runs = 1

  dynamic "task" {
    for_each = var.ingestion_pipelines
    content {
      task_key = "${task.key}-ingestion"
      pipeline_task {
        pipeline_id = task.value
      }
      run_if = "ALL_SUCCESS"
    }
  }

  schedule {
    quartz_cron_expression = var.schedule.quartz_cron_expression
    timezone_id            = var.schedule.timezone_id
  }
}

# Create individual jobs per schedule group (for per-database scenario)
# Each job contains multiple pipeline tasks for all databases in that schedule group
resource "databricks_job" "individual_orchestrator" {
  count = var.is_common_job ? 0 : 1

  name                = var.name
  max_concurrent_runs = 1

  dynamic "task" {
    for_each = var.ingestion_pipelines
    content {
      task_key = "${task.key}-ingestion"
      pipeline_task {
        pipeline_id = task.value
      }
      run_if = "ALL_SUCCESS"
    }
  }

  schedule {
    quartz_cron_expression = var.schedule.quartz_cron_expression
    timezone_id            = var.schedule.timezone_id
  }
}

resource "databricks_permissions" "common_job_perms" {
  count  = (var.is_common_job && length(var.permissions) > 0) ? 1 : 0
  job_id = databricks_job.common_orchestrator_all_pipelines[0].id

  dynamic "access_control" {
    for_each = var.permissions
    content {
      user_name              = try(access_control.value.user_name, null)
      group_name             = try(access_control.value.group_name, null)
      service_principal_name = try(access_control.value.service_principal_name, null)
      permission_level       = access_control.value.level
    }
  }
}

resource "databricks_permissions" "individual_job_perms" {
  count  = (!var.is_common_job && length(var.permissions) > 0) ? 1 : 0
  job_id = databricks_job.individual_orchestrator[0].id

  dynamic "access_control" {
    for_each = var.permissions
    content {
      user_name              = try(access_control.value.user_name, null)
      group_name             = try(access_control.value.group_name, null)
      service_principal_name = try(access_control.value.service_principal_name, null)
      permission_level       = access_control.value.level
    }
  }
}

output "common_orchestrator_all_pipelines" {
  value = var.is_common_job ? { (var.name) = databricks_job.common_orchestrator_all_pipelines[0].id } : {}
}

output "individual_orchestrator" {
  value = var.is_common_job ? {} : { (var.name) = databricks_job.individual_orchestrator[0].id }
} 