terraform {
  # Uncomment below line for using local backend for state storage in local deployments . The state file will be stored locally at: infra/terraform.tfstate
  backend "local" {}
  
  # For CI/CD deployments in production or for team collaboration, use remote backend
  #backend "azurerm" {
  #  resource_group_name  = "ps-west-europe"
  #  storage_account_name = "pswesteuropestorage"
  #  container_name       = "tf-state"
  #  key                  = "lakeflow-connect-cicd-full-refresh-demo.tfstate"
  #  use_azuread_auth     = true
  #}
  
}