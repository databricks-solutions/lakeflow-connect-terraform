# Config-driven Terraform deployment of Lakeflow Connect connectors

This project is intended to deploy and scale out database connectors to the Databricks Lakehouse platform using infrastructure-as-code principles.
It is intended to be a database-agnostic, YAML-driven Terraform deployment for Databricks Lakeflow Connect that provides built-in validation and orchestration for deployments.

## Quick Visual Tour

![Quick Visual Tour Animation](docs/assets/images/lakeflow-connect-terraform.gif)



## Key Features:
- **Database-agnostic**: Supports various Lakeflow Connect-supported databases by simply changing the `source_type` in the config.
    - Currently tested and verified connectors are:
        - SQL Server CDC ([Public docs](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-pipeline))
        - PostgreSQL CDC ([Public docs](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/postgresql-pipeline))
        - Oracle (public docs to be added once in public preview)
        - MySQL ([Public docs](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/mysql-pipeline))
- **YAML-driven configuration**: Define connections, databases, schemas, tables, and schedules in a single configuration file
- **Flexible Unity Catalog mapping**: Configure where data lands with per-database catalog and schema customization
- **Flexible ingestion modes**: Choose between full schema ingestion or specific table selection per database
- **Automated orchestration**: Configurable job scheduling of the managed ingestion pipelines with support for multiple sync frequencies
- **Infrastructure-as-Code**: Fully automated deployment of gateway pipelines, ingestion pipelines, and orchestration jobs

**What gets deployed:**
- Lakeflow Connect gateway pipeline, using an existing Unity Catalog connection
- Ingestion pipelines for each database/schema combination, all routed through a single shared gateway
- Databricks jobs to orchestrate the ingestion workflows
- Optional: Event log tables for pipeline monitoring

## Overview

This project deploys a subset of the architecture shown below, focusing on infrastructure needed to run Lakeflow Connect data ingestion. Specifically, this project will deploy:

- The Lakeflow Connect Gateway pipeline, using a pre-existing Unity Catalog connection (**Note:** The connection itself is not created or managed by this project)
- Managed Ingestion pipelines for each configured database/schema/table combination, as defined in your YAML configuration
- Databricks Jobs to orchestrate and schedule the ingestion pipeline workflows
- (Optional) Event log tables used for pipeline monitoring and audit (created if configured in your YAML)


![Lakeflow Connect Architecture Overview](docs/assets/images/lakeflow_connect_architecture.png)


## Project Layout

```
lakeflow-connect-terraform/
├── config/                      # YAML configuration files
│   ├── lakeflow_dev.yml        # Active configuration
│   └── examples/                # Example configurations
│       ├── mysql.yml             # MySQL example
│       ├── oracle.yml            # Oracle example
│       ├── postgresql.yml        # PostgreSQL example
│       └── sqlserver.yml         # SQL Server example
├── infra/                       # Terraform root module
│   ├── backend.tf
│   ├── backend.local.tfvars.example  # Copy to backend.local.tfvars (non-secrets only; gitignored)
│   ├── main.tf
│   ├── locals.tf
│   ├── outputs.tf
│   ├── provider.tf
│   ├── variables.tf
│   └── modules/
│       ├── gateway_pipeline/
│       ├── ingestion_pipeline/
│       ├── job/
│       ├── gateway_validation/
│       └── validate_catalog_and_schemas/
├── tools/                       # Validation scripts (optional)
│   ├── pydantic_validator.py    # Type-safe YAML validation (recommended)
│   └── validate_running_gateway.py
├── pyproject.toml              # Python dependencies for validation tools
└── README.md
```

## Pre-requisites

### Software Requirements
- **Terraform** >= 1.10
- **Databricks Terraform Provider** >= 1.104.0 (for PostgreSQL source_configurations support)
- **Databricks workspace** with Unity Catalog enabled
- **Python 3.10+** and **Poetry** (optional, for YAML validation tools)

### Databricks Setup

#### 1. Create Unity Catalog Connection
Create a Databricks Unity Catalog connection to your source database and specify it in your YAML config under `connection.name`.

Refer to Databricks documentation for your database type:
- [SQL Server Connection Setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-overview)
- [PostgreSQL Connection Setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/postgresql-source-setup)
- [MySQL Connection Setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/mysql-privileges)
- **Oracle**: Create a Unity Catalog connection to your Oracle source. (public docs to be added once in public preview)

#### 2. Create Unity Catalog Structure
Based on your YAML configuration in the `unity_catalog` section, pre-create:

- **Catalogs**: Create catalog(s) specified in `global_uc_catalog` and `staging_uc_catalog` (if different)
- **Staging Schema**: Create the schema specified in `staging_schema` within the staging catalog
- **Ingestion Schemas**: Create schemas for ingestion pipelines in their target catalogs
  - Schema names will be: `{schema_prefix}{source_schema_name}{schema_suffix}`
  - Example: If source schema is `dbo` with prefix `dev_` → create schema `dev_dbo`
  - If no prefix/suffix specified, use the source schema name as-is

#### 3. Configure Source Database (Database-Specific)

**For PostgreSQL Sources:**
Pre-create replication slots and publications in the source database and specify in the YAML config ( see `config/examples/postgresql.yml`)

Refer to [PostgreSQL Replication Setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/postgresql-source-setup) for detailed instructions.

**For SQL Server Sources:**
Ensure CDC is enabled on the source database and tables. Refer to [SQL Server CDC Setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-pipeline).

**For Oracle Sources:**
In your YAML config, set `connection.source_type: "ORACLE"` and provide `connection.connection_parameters.source_catalog` with your Oracle CDB (container database) name (e.g. `ORCLCDB`). See `config/examples/oracle.yml`. (public docs to be added once in public preview)

**For MySQL Sources:**
MySQL has no schema level (server → database → tables). In the YAML, list each database and under `schemas` use a placeholder name (e.g. `"<not applicable in MySQL>"`) and list tables by their **full MySQL table name**. Set `connection.source_type: "MYSQL"`. If you set `use_schema_ingestion: true`, it is ignored and ingestion uses the tables list; the Pydantic validator prints an info message when you run it. See `config/examples/mysql.yml`.

#### 4. Grant Permissions
Provide the user/SPN used for Terraform deployment with:

- `USE CONNECTION` on the Unity Catalog connection to the source database
- `USE CATALOG` on all catalogs specified in your YAML config
- `USE SCHEMA` and `CREATE TABLE` on all ingestion pipeline target schemas
- `USE SCHEMA`, `CREATE TABLE` and `CREATE VOLUME` on the staging schema
  - Note: `CREATE TABLE` allows creation of event log tables if enabled
- Access to cluster policy for spinning up gateway pipeline compute ([Policy Documentation](https://docs.databricks.com/aws/en/admin/clusters/policy-definition))
  - Specify the policy name in your YAML config under `gateway_pipeline_cluster_policy_name`

### Assumptions
1. **Unity Catalog Resources**: All Unity Catalog catalogs and schemas specified in the YAML configuration must already exist. This project validates their existence but does not create them.
2. **Database Permissions**: The database replication user used with the Unity Catalog connection must have all necessary permissions on the source database.
3. **Source Database Configuration**: For PostgreSQL, replication slots and publications must be pre-created. For SQL Server, CDC must be enabled.

## Installation

### Step 1: Clone and Configure

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

### Step 2: (Optional) Set Up Python Validation Tools

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

After validation passes, proceed with Terraform deployment (no Poetry needed).

### Step 3: Configure Authentication

Set up authentication for Databricks workspace Terraform provider:

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

### Step 4: Configure Terraform Backend

Terraform stores [state](https://developer.hashicorp.com/terraform/language/state) in a **backend**. This repository ships with **`azurerm` (Azure Blob Storage)** as an **example** of a **remote** backend for teams and CI; you can swap it for any other [supported backend](https://developer.hashicorp.com/terraform/language/settings/backends) (Amazon S3, Google Cloud Storage, Terraform Cloud, etc.) by changing `infra/backend.tf` and following that backend’s init instructions.

**Who touches the state blob (remote `azurerm` example only)**

State in Azure Storage is **not** opened using whatever you set in `ARM_CLIENT_ID` for deployment unless you deliberately use the **same** app registration for both roles.

| Identity | Purpose | When it is used |
|----------|---------|-----------------|
| **TF state SPN** | **Only** Azure Blob access for the Terraform state file | Supplied at **`terraform init`** time—via **environment variables** (recommended) and/or `-backend-config` flags that reference them—**not** by committing secrets in a repo file. This principal **does not** deploy Databricks resources; it only needs access to the state container/blob. |
| **Deploy SPN** | Databricks (and any Azure usage your root module expects via providers) | **`ARM_*` and `DATABRICKS_*` during `terraform plan` / `apply`**—this is a **different** service principal in the recommended setup. |

**Recommended:** use **two** Azure AD applications (two client IDs): one for state, one for deploy.  
**Alternative:** a single app registration can fill both roles; then you may reuse the same values in env vars for init and for `ARM_*` during plan/apply—still use an explicit init step (file + `-backend-config` for credentials from env) so it is obvious which identity touches the state blob.

**Azure permissions for the TF state SPN (Blob backend with `use_azuread_auth=true`)**

The Entra ID application whose **client ID** you pass at init (for example via `TF_STATE_ARM_CLIENT_ID` and the matching secret) must be able to read and write the state blob. At minimum, assign that principal **[Storage Blob Data Contributor](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#storage-blob-data-contributor)** on the **Azure Storage blob container** that holds Terraform state (or on the parent **storage account** if you prefer a broader scope).

Grant this principal **data-plane** access via Azure RBAC, not storage account keys:

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

#### Option B — Remote backend (example: Azure Storage / `azurerm`) - This is recommended, if one has access to a remote backend state store while developing.

`infra/backend.tf` uses an **empty** `backend "azurerm" {}` block ([partial configuration](https://developer.hashicorp.com/terraform/language/settings/backends#partial-configuration)).  
**Do not commit secrets:** keep storage **names** (and similar non-secrets) in a local file if you want; keep **TF state SPN** credentials in **environment variables** (or your CI/secret manager) and pass them into `terraform init` as shown below (same idea as the GitHub Actions workflows, which inject secrets as env-backed `terraform init` arguments).

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

   You can load these from a process manager, `direnv`, or a **gitignored** `.env` file (this repo already ignores `.env`) and never commits them.

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

5. For **plan/apply**, set environment variables for the **deploy** SPN and then run Terraform:  
**Note:** - `DATABRICKS_CONFIG_PROFILE` env var is used below, however there are several other options to auth to Databricks. Refer to [Databricks Terraform provider Authentication documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs#authentication) for other options.

   ```bash
   export DATABRICKS_CONFIG_PROFILE=<Config profile of choice of Deploy SPN with access to Databricks assets>

   poetry run terraform plan  --var yaml_config_path=../config/lakeflow_<env>.yml
   poetry run terraform apply --var yaml_config_path=../config/lakeflow_<env>.yml
   ```

**Equivalent `terraform init` (CI or fully inline)**

From `infra/`, you can pass the same non-secret keys as in `backend.local.tfvars` via repeated `-backend-config` flags (see `.github/workflows/terraform-deploy.yml` and `terraform-release.yml`). Supply **TF state** authentication the same way as locally: **secrets from environment variables** (CI: GitHub Actions secrets), not from committed files—for example:

- `resource_group_name`, `storage_account_name`, `container_name`, `key`
- `use_azuread_auth=true` (when using Azure AD / RBAC on the storage account)
- `client_id`, `client_secret`, `subscription_id`, `tenant_id` for the **TF state** SPN via `-backend-config="..."` populated from your secret store or `${TF_STATE_ARM_*}` in a shell

**GitHub Actions (this repo’s `azurerm` example)**

Configure these **repository variables** (non-secret identifiers for the state blob):

- `TF_STATE_RESOURCE_GROUP`
- `TF_STATE_STORAGE_ACCOUNT`
- `TF_STATE_CONTAINER`
- `TF_STATE_KEY`

Workflows pass them with `terraform init` alongside the TF state SPN **secrets** (`TF_STATE_ARM_*`, `ARM_TENANT_ID`). Plan/apply jobs set `ARM_*` to the **deploy** SPN.

**Other remote backends**

If you do not use Azure Blob, replace the backend block in `infra/backend.tf` with your chosen backend and follow HashiCorp’s documentation for that provider; the **deploy** SPN and YAML-driven Databricks resources stay the same—only state storage and `terraform init` differ.

### Step 5: Deploy Infrastructure

Run Terraform via `poetry run` so that the gateway validation step (which runs a Python script using the Databricks SDK) has access to the project's Python dependencies.

```bash
# Plan deployment (review changes)
poetry run terraform plan --var yaml_config_path=../config/lakeflow_<env>.yml

# Apply deployment
poetry run terraform apply --var yaml_config_path=../config/lakeflow_<env>.yml
```

**Note:** While `terraform plan` does not require `poetry run` (since the gateway validation Python script is executed only during `apply`), we recommend using `poetry run` for both `plan` and `apply` to provide a consistent workflow and environment.

## GitHub Actions CI/CD Setup

This repository ships with five GitHub Actions workflows that run on a **self-hosted runner** and automate the full deployment and refresh lifecycle.

### Workflows Overview

| Workflow file | Trigger | Purpose |
|---------------|---------|---------|
| `terraform-deploy.yml` | Push to `main` (auto plan) or `workflow_dispatch` | Validate → Plan → Apply (with optional approval gate) |
| `terraform-release.yml` | Semver tag push (e.g. `v1.0.0`) | Tag-gated Validate → Plan → Apply; tag must be tip of `main` |
| `terraform-output-pipeline-ids.yml` | `workflow_dispatch` | Read-only: list all pipeline IDs from Terraform state |
| `full-refresh-pipeline.yml` | `workflow_dispatch` | Trigger a full refresh of an entire ingestion pipeline |
| `full-refresh-tables.yml` | `workflow_dispatch` | Trigger a full refresh of specific tables within a pipeline |

### Self-Hosted Runner Prerequisites

All workflows use `runs-on: self-hosted`. The runner machine must have:

- **Terraform** >= 1.10 available on `PATH`
- **Python venv activated** — the workflows use `python` (not `python3`). Activate the project's Poetry-managed venv in the runner's startup shell so that `python`, `pip`, and all SDK dependencies resolve correctly:

  ```bash
  source /path/to/poetry/virtualenvs/lakeflow-connect-terraform-<hash>-py3.XX/bin/activate
  ```

  To find the venv path on your machine:
  ```bash
  poetry env list --full-path
  ```

### Required Repository Secrets

Configure these under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Description | Used by |
|--------|-------------|---------|
| `ARM_TENANT_ID` | Azure AD tenant ID — shared by both SPNs | All workflows |
| `DATABRICKS_HOST` | Databricks workspace URL (e.g. `https://adb-xxx.azuredatabricks.net`) | All workflows |
| `TF_STATE_ARM_CLIENT_ID` | Client ID of the **TF State SPN** — authenticates to Azure Blob backend | `terraform-deploy`, `terraform-release`, `terraform-output-pipeline-ids` |
| `TF_STATE_ARM_CLIENT_SECRET` | Client secret of the TF State SPN | same as above |
| `TF_STATE_ARM_SUBSCRIPTION_ID` | Azure subscription ID that contains the TF state storage account | same as above |
| `DEPLOY_SPN_CLIENT_ID` | Client ID of the **Deploy SPN** — used by the Databricks Terraform provider and SDK | All workflows |
| `DEPLOY_SPN_CLIENT_SECRET` | Client secret of the Deploy SPN | All workflows |

> **Two-SPN model:** `TF_STATE_*` credentials authenticate only to Azure Blob Storage (Terraform state); they never touch Databricks. `DEPLOY_SPN_*` credentials are the Databricks-registered service principal used for `terraform plan/apply`, Databricks SDK calls, and reading Terraform state outputs — consistently across all workflows. No PAT tokens are used. See the [Terraform Backend section](#step-4-configure-terraform-backend) for the full explanation.

### Required Repository Variables

Configure these under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Description | Used by |
|----------|-------------|---------|
| `TF_STATE_RESOURCE_GROUP` | Azure Resource Group containing the TF state storage account | `terraform-deploy`, `terraform-release`, `terraform-output-pipeline-ids` |
| `TF_STATE_STORAGE_ACCOUNT` | Azure Storage Account name | same as above |
| `TF_STATE_CONTAINER` | Blob container name within the storage account | same as above |
| `TF_STATE_KEY` | Blob path/filename for the `.tfstate` file (e.g. `lakeflow-connect/terraform.tfstate`) | same as above |

### Optional: GitHub Environments for Approval Gates

The deploy and refresh workflows support human approval gates via [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment). To enable them:

1. Create an environment named **`production-deploy`** (for Terraform apply) and/or **`production-refresh`** (for pipeline refresh jobs) under **Settings → Environments**.
2. Add required reviewers to each environment.
3. Uncomment the `environment:` block in the relevant workflow job (search for `# environment:` in the workflow files).

> Approval gates require **GitHub Pro, Team, or Enterprise** for private repositories.

## YAML Configuration

See `config/examples/` for complete example configurations ([MySQL](config/examples/mysql.yml), [Oracle](config/examples/oracle.yml), [PostgreSQL](config/examples/postgresql.yml), [SQL Server](config/examples/sqlserver.yml)). The configuration is fully YAML-driven with the following main sections:

### Connection
```yaml
connection:
  name: "my_uc_connection"
  source_type: "POSTGRESQL"  # POSTGRESQL, SQLSERVER, MYSQL, ORACLE

# Oracle only: required when source_type is ORACLE (CDB name for gateway)
# connection_parameters:
#   source_catalog: "ORCLCDB"
```

### Unity Catalog Configuration
```yaml
unity_catalog:
  global_uc_catalog: "my_catalog"      # Required: Default catalog for ingestion pipelines
  staging_uc_catalog: "staging_cat"    # Optional: Catalog for gateway staging (defaults to global)
  staging_schema: "lf_staging"         # Optional: Schema for gateway staging (defaults to {app_name}_lf_staging)
```

- `global_uc_catalog`: Default catalog where ingestion pipeline tables land (required)
- `staging_uc_catalog`: Catalog for gateway pipeline staging assets (optional, defaults to `global_uc_catalog`)
- `staging_schema`: Schema name for gateway staging assets (optional, defaults to `{app_name}_lf_staging`)

### Databases
```yaml
databases:
  - name: my_database
    # Optional: Override global catalog for this database
    uc_catalog: "custom_catalog"
    
    # Optional: Customize schema names
    schema_prefix: "dev_"      # Results in: dev_<schema_name>
    schema_suffix: "_raw"      # Results in: <schema_name>_raw
    
    # PostgreSQL only: Replication configuration
    replication_slot: "dbx_slot_mydb"
    publication: "dbx_pub_mydb"
    
    schemas:
      - name: public
        use_schema_ingestion: true  # Ingest all tables
      - name: app_schema
        use_schema_ingestion: false  # Ingest specific tables only
        tables:
          - source_table: users
          - source_table: orders
          # Optional per-table overrides (default to schema/database-level catalog and schema):
          - source_table: orders_archive
            destination_table: orders_archive_v2  # optional
            destination_catalog: other_catalog   # optional
            destination_schema: other_schema    # optional
```

- Per-database `uc_catalog`: Override global catalog for specific database (optional)
- Per-database `schema_prefix` and `schema_suffix`: Customize destination schema names (optional)
- Per-database `replication_slot` and `publication`: PostgreSQL replication configuration (PostgreSQL only)
- Schemas and tables to ingest with granular control
- Per-table destination overrides: For table-level ingestion (`use_schema_ingestion: false`), each table can optionally specify `destination_table`, `destination_catalog`, and `destination_schema`. When set, they override the pipeline default (from database/schema config). Catalogs and schemas used by per-table overrides are validated and must exist in Unity Catalog.

### Event Logs
```yaml
event_log:
  to_table: true  # Enable/disable materialization of event logs to Delta tables
```

### Job Orchestration
```yaml
job:
  common_job_for_all_pipelines: false
  common_schedule:
    quartz_cron_expression: "0 */30 * * * ?"
    timezone_id: "UTC"
  
  # Per-database schedules (when common_job_for_all_pipelines is false)
  per_database_schedules:
    - name: "frequent_sync"
      applies_to: ["db1", "db2"]
      schedule:
        quartz_cron_expression: "0 */15 * * * ?"
        timezone_id: "UTC"
```

Supports two scheduling modes:
1. **Common job for all pipelines** (`common_job_for_all_pipelines: true`): Single job runs all database ingestion pipelines on the same schedule
2. **Per-database scheduling** (`common_job_for_all_pipelines: false`): Separate jobs per schedule group, allowing different databases to sync at different frequencies

## How does it compare to other deployment options?

| Feature | This Project (Terraform) | Databricks CLI | DABS | REST API | UI |
|---------|-------------------------|----------------|------|----------|-----|
| **Infrastructure-as-Code** | ✅ Native | ⚠️ Limited | ✅ Yes | ❌ No | ❌ No |
| **Version Control** | ✅ Git-native | ⚠️ Manual | ✅ Git-native | ❌ Manual | ❌ Manual |
| **Multi-environment** | ✅ Built-in | ⚠️ Manual | ✅ Built-in | ⚠️ Manual | ❌ Manual |
| **State Management** | ✅ Native | ❌ None | ⚠️ Limited | ❌ None | ❌ None |
| **YAML-driven** | ✅ Yes | ❌ No | ✅ Yes | ❌ No | ❌ No |
| **Validation** | ✅ Pre-deploy | ❌ No | ⚠️ Limited | ❌ No | ⚠️ Post-deploy |
| **Team Collaboration** | ✅ Excellent | ⚠️ Manual | ✅ Good | ❌ Poor | ❌ Poor |
| **Learning Curve** | ⚠️ Moderate | ✅ Easy | ⚠️ Moderate | ⚠️ Complex | ✅ Easy |
| **Automation-friendly** | ✅ Excellent | ✅ Good | ✅ Good | ✅ Excellent | ❌ Poor |

**When to use Terraform (this project):**
- Managing multiple environments (dev, staging, prod)
- Team collaboration with state management
- Complex configurations with many pipelines
- CI/CD automation requirements
- Need for validation before deployment

**When to use alternatives:**
- **UI**: Quick one-off deployments, learning/exploration
- **CLI**: Simple scripts, single-pipeline deployments
- **DABS**: Databricks-native workflows with asset bundles
- **API**: Custom integrations, programmatic control

## How to get help

Databricks support doesn't cover this content. For questions or bugs, please open a GitHub issue and the team will help on a best effort basis.

## Future Enhancements

- Pre-commit hooks for YAML validation
- Pydantic-based schema validation
- Automated CI/CD pipeline examples
- Metadata export for downstream applications
- Cost estimation based on configuration
- Multi-region deployment support

## License

© 2025 Databricks, Inc. All rights reserved. The source in this notebook is provided subject to the [Databricks License](https://databricks.com/db-license-source). All included or referenced third party libraries are subject to the licenses set forth below.

| library                                | description             | license    | source                                              |
|----------------------------------------|-------------------------|------------|-----------------------------------------------------|
| terraform-provider-databricks          | Databricks provider     | Apache 2.0 | https://github.com/databricks/terraform-provider-databricks |
