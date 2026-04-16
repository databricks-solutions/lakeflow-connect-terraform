# Installation Guide

> This guide covers local setup and deployment from your workstation. For automated CI/CD deployment, see [GitHub Actions CI/CD Setup](cicd-setup.md).

## Step 1: Clone and Configure

```bash
# Clone the repository
git clone <your-repo-url>
cd lakeflow-connect-terraform

# Copy an example configuration and customize for your environment
# For PostgreSQL:
cp config/examples/postgresql.yml config/lakeflow_<your_env>.yml

# For SQL Server:
cp config/examples/sqlserver.yml config/lakeflow_<your_env>.yml

# For Oracle:
cp config/examples/oracle.yml config/lakeflow_<your_env>.yml

# For MySQL:
cp config/examples/mysql.yml config/lakeflow_<your_env>.yml

# Edit the YAML file with your environment details
```

## Step 2: (Optional) Set Up Python Validation Tools

The Python tools provide **type-safe YAML validation** using Pydantic **before** Terraform deployment. This catches configuration errors early with detailed error messages. **Note**: Terraform itself does not require Poetry. It reads YAML directly using the built-in `yamldecode()` function.

```bash
# Install Poetry (if not already installed)
pip install poetry

# Install project dependencies (includes Pydantic, croniter, etc.)
poetry install

# Validate your configuration before deploying
poetry run python tools/pydantic_validator.py config/lakeflow_<your_env>.yml
```

**What gets validated:**
- ✅ **Type safety**: Boolean values must be `true/false`, not strings
- ✅ **Source-specific config**: PostgreSQL requires `replication_slot` and `publication`; Oracle requires `connection_parameters.source_catalog` (CDB name)
- ✅ **Cross-references**: Database names in schedules must exist
- ✅ **Unity Catalog logic**: Validates catalog configuration rules
- ✅ **Cron expressions**: Validates Quartz cron syntax
- ✅ **Schema naming**: Validates prefix/suffix contain valid characters
- ✅ **Table requirements**: Ensures tables are specified when needed

After validation passes, proceed with Terraform deployment (no Poetry needed for Terraform itself).

## Step 3: Configure Authentication

Set up authentication for the Databricks workspace Terraform provider:

**Option A: Personal Login (Development)**
```bash
# For Azure
az login
export DATABRICKS_HOST="https://adb-xxxxx.azuredatabricks.net"
export DATABRICKS_AUTH_TYPE="azure-cli"
```

**Option B: Service Principal**
```bash
# Create profile in ~/.databrickscfg
cat >> ~/.databrickscfg << EOF
[production]
host                = https://adb-<workspace_id>.<num>.azuredatabricks.net/
azure_tenant_id     = <tenant_id>
azure_client_id     = <client_id>
azure_client_secret = <client_secret>
auth_type           = azure-client-secret
EOF

# Set environment variable
export DATABRICKS_CONFIG_PROFILE=production
```

> **CI/CD:** For GitHub Actions deployments, authentication uses a dedicated Deploy SPN with `ARM_*` environment variables rather than `az login` or a config profile. See [GitHub Actions CI/CD Setup](cicd-setup.md) for details.

## Step 4: Configure Terraform Backend

Terraform stores [state](https://developer.hashicorp.com/terraform/language/state) in a **backend**. This repository ships with **`azurerm` (Azure Blob Storage)** as an **example** of a **remote** backend for teams and CI; you can swap it for any other [supported backend](https://developer.hashicorp.com/terraform/language/settings/backends) (Amazon S3, Google Cloud Storage, Terraform Cloud, etc.) by changing `infra/backend.tf` and following that backend's init instructions.

**Who touches the state blob (remote `azurerm` example only)**

State in Azure Storage is **not** opened using whatever you set in `ARM_CLIENT_ID` for deployment unless you deliberately use the **same** app registration for both roles.

| Identity | Purpose | When it is used |
|----------|---------|-----------------|
| **TF state SPN** | **Only** Azure Blob access for the Terraform state file | Supplied at **`terraform init`** time—via **environment variables** (recommended) and/or `-backend-config` flags that reference them—**not** by committing secrets in a repo file. This principal **does not** deploy Databricks resources; it only needs access to the state container/blob. |
| **Deploy SPN** | Databricks (and any Azure usage your root module expects via providers) | **`ARM_*` environment variables during `terraform plan` / `apply`**—this is a **different** service principal in the recommended setup. |

**Recommended:** use **two** Azure AD applications (two client IDs): one for state, one for deploy.  
**Alternative:** a single app registration can fill both roles; then you may reuse the same values in env vars for init and for `ARM_*` during plan/apply—still use an explicit init step (file + `-backend-config` for credentials from env) so it is obvious which identity touches the state blob.

**Azure permissions for the TF state SPN (Blob backend with `use_azuread_auth=true`)**

The Entra ID application whose **client ID** you pass at init must be able to read and write the state blob. At minimum, assign that principal **[Storage Blob Data Contributor](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#storage-blob-data-contributor)** on the **Azure Storage blob container** that holds Terraform state (or on the parent **storage account** if you prefer a broader scope).

- **Minimum:** **Storage Blob Data Contributor** scoped to the state **container** is sufficient for typical state locking and read/write.
- `use_azuread_auth=true` means Terraform authenticates to Blob Storage with Azure AD; the SPN must be able to read and write that blob.

---

#### Option A — Local backend (simple / single user)

In `infra/backend.tf`, comment out `backend "azurerm" {}` and uncomment `backend "local" {}` (only one backend block may be active). Then:

```bash
cd infra
terraform init -reconfigure
terraform validate
```

State file path: `infra/terraform.tfstate`. Do not commit that file if you later move to shared remote state. No TF state SPN or Azure storage setup is required for this option.

---

#### Option B — Remote backend (example: Azure Storage / `azurerm`)

This is recommended when you have access to a remote backend state store — essential for teams and CI.

`infra/backend.tf` uses an **empty** `backend "azurerm" {}` block ([partial configuration](https://developer.hashicorp.com/terraform/language/settings/backends#partial-configuration)).  
**Do not commit secrets:** keep storage **names** (and similar non-secrets) in a local file if you want; keep **TF state SPN** credentials in **environment variables** (or your CI/secret manager) and pass them into `terraform init` as shown below.

**Local / team: non-secret file + env vars for the TF state SPN**

1. Copy the example and fill in **only** non-secret values (the copy is Git ignored by `*.tfvars`):

   ```bash
   cp infra/backend.local.tfvars.example infra/backend.local.tfvars
   ```

2. Edit `infra/backend.local.tfvars` with your storage account, container, and state blob **key**—**not** client IDs or secrets.

3. Export the **TF state SPN** in your shell (names are suggestions; align with the `terraform init` command you use):

   ```bash
   export TF_STATE_ARM_CLIENT_ID="<tf_state_app_id>"
   export TF_STATE_ARM_CLIENT_SECRET="<tf_state_secret>"
   export TF_STATE_ARM_SUBSCRIPTION_ID="<subscription_for_state_blob>"
   export TF_STATE_ARM_TENANT_ID="<tenant_id>"
   ```

   You can load these from a process manager, `direnv`, or a **gitignored** `.env` file (this repo already ignores `.env`) and never commit them.

4. Initialize from `infra/` so credentials come from the environment (shell expands the variables; nothing secret is stored on disk in tracked files):

   ```bash
   cd infra
   terraform init -reconfigure \
     -backend-config=backend.local.tfvars \
     -backend-config="client_id=${TF_STATE_ARM_CLIENT_ID}" \
     -backend-config="client_secret=${TF_STATE_ARM_CLIENT_SECRET}" \
     -backend-config="subscription_id=${TF_STATE_ARM_SUBSCRIPTION_ID}" \
     -backend-config="tenant_id=${TF_STATE_ARM_TENANT_ID}"
   terraform validate
   ```

5. For **plan/apply**, set environment variables for the **deploy** SPN and then run Terraform.  
   **Note:** `DATABRICKS_CONFIG_PROFILE` is one option; refer to [Databricks Terraform provider Authentication documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs#authentication) for all supported auth methods.

   ```bash
   export DATABRICKS_CONFIG_PROFILE=<profile of Deploy SPN with access to Databricks assets>

   poetry run terraform plan  --var yaml_config_path=../config/lakeflow_<env>.yml
   poetry run terraform apply --var yaml_config_path=../config/lakeflow_<env>.yml
   ```

**Other remote backends**

If you do not use Azure Blob, replace the backend block in `infra/backend.tf` with your chosen backend and follow HashiCorp's documentation for that provider; the Deploy SPN and YAML-driven Databricks resources stay the same — only state storage and `terraform init` differ.

> **CI/CD:** GitHub Actions workflows pass backend credentials via `-backend-config` flags populated from GitHub Actions secrets and variables. See [GitHub Actions CI/CD Setup](cicd-setup.md) for the full reference.

---

## Step 5: Deploy Infrastructure

Run Terraform via `poetry run` so that the gateway validation step (which runs a Python script using the Databricks SDK) has access to the project's Python dependencies.

```bash
# Plan deployment (review changes)
poetry run terraform plan --var yaml_config_path=../config/lakeflow_<env>.yml

# Apply deployment
poetry run terraform apply --var yaml_config_path=../config/lakeflow_<env>.yml
```

**Note:** While `terraform plan` does not require `poetry run` (the gateway validation Python script runs only during `apply`), using `poetry run` for both provides a consistent environment.
