provider "databricks" {
  # Authentication is configured entirely via environment variables.
  #
  # Local development (azure-cli):
  #   `DATABRICKS_HOST      = workspace URL` and `DATABRICKS_AUTH_TYPE = azure-cli`
  #   or 
  #   `DATABRICKS_CONFIG_PROFILE` if preferred
  #
  # CI/CD (service principal via Entra ID azure-client-secret):
  #   DATABRICKS_HOST                = workspace URL
  #   DATABRICKS_AZURE_CLIENT_ID     = DEPLOY_SPN Entra ID application (client) ID
  #   DATABRICKS_AZURE_CLIENT_SECRET = DEPLOY_SPN Entra ID client secret
  #   DATABRICKS_AZURE_TENANT_ID     = Azure AD tenant ID
  #
  # In CI/CD, these env vars are set in the shell after unsetting ARM_*
  # (which are used by the azurerm backend for terraform state).
}
