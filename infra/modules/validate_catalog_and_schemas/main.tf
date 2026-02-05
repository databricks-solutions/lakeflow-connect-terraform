variable "catalog_name" {
  type = string
}

variable "schemas" {
  type    = list(string)
  default = []
}

# Validate that the catalog exists
data "databricks_catalog" "this" {
  name = var.catalog_name
}

# Validation check - this will fail if schemas don't exist
data "databricks_schema" "schemas" {
  for_each = toset(var.schemas)
  name     = "${data.databricks_catalog.this.name}.${each.value}"
}

output "catalog_name" {
  value = data.databricks_catalog.this.name
} 