terraform {
  # ---------------------------------------------------------------------------
  # Backends: enable exactly ONE of the blocks below (uncomment one, comment the
  # other). Terraform allows only a single backend block per configuration.
  # ---------------------------------------------------------------------------

  # Option A — Remote state (Recommended for teams / CI. Suitable for Production)
  #   `azurerm` shown as example. Adapt to other remote backends as needed.
  #   Intentionally set as Partial / "empty" backend
  #   During `terraform init` pass along settings ( see README for more details)

  backend "azurerm" {}

  # Option B — Local filesystem state (legacy / single-user option for local state)
  #   Uncomment `backend "local" {}` below, comment out `backend "azurerm" {}`,
  #   then `terraform init`. State file path: infra/terraform.tfstate (relative to the working directory)

  # backend "local" {}
}
