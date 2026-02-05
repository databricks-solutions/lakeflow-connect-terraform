terraform {
  # Using local backend for state storage
  # State file will be stored locally at: infra/terraform.tfstate
  
  # For team collaboration, replace with a remote backend:
  # Example:
  # backend "azurerm" {
  #   resource_group_name  = "terraform-state-rg"
  #   storage_account_name = "tfstatelakeflow"
  #   container_name       = "tfstate"
  #   key                  = "lakeflow-connect.tfstate"
  # }
  # Then run: terraform init -reconfigure
  
  backend "local" {}
}