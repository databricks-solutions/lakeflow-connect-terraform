provider "databricks" {
  # Authentication is configured entirely via environment variables.
  # The Databricks unified auth layer tries methods in priority order and stops
  # at the first success. Set only the variables for your target cloud/method.
  #
  # Local development:
  #   Azure: az login, then DATABRICKS_HOST + DATABRICKS_AUTH_TYPE=azure-cli
  #   Any:   DATABRICKS_CONFIG_PROFILE pointing to a profile in ~/.databrickscfg
  #
  # CI/CD — Option A: OAuth M2M (Azure or AWS workspaces, recommended):
  #   DATABRICKS_HOST          = workspace URL
  #   DATABRICKS_CLIENT_ID     = Databricks service principal OAuth client ID
  #   DATABRICKS_CLIENT_SECRET = Databricks service principal OAuth client secret
  #
  # CI/CD — Option B: Azure SPN / Entra ID (Azure workspaces only):
  #   DATABRICKS_HOST  = workspace URL
  #   ARM_CLIENT_ID    = DEPLOY_SPN Entra ID application (client) ID
  #   ARM_CLIENT_SECRET = DEPLOY_SPN Entra ID client secret
  #   ARM_TENANT_ID    = Azure AD tenant ID
  #
  # Note: ARM_* vars are also used by the azurerm backend for Terraform state.
  # The backend uses TF_STATE_ARM_* secrets (separate SPN); the Databricks
  # provider uses DEPLOY_SPN ARM_* secrets for plan/apply.
}
