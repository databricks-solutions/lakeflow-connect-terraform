terraform {
  required_version = ">= 1.10"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.104.0"
    }
  }
} 