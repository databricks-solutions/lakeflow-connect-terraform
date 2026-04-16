# Config-driven Terraform deployment of Lakeflow Connect connectors

This project is intended to deploy and scale out database connectors to the Databricks Lakehouse platform using infrastructure-as-code principles.
It is intended to be a database-agnostic, YAML-driven Terraform deployment for Databricks Lakeflow Connect that provides built-in validation and orchestration for deployments.

The project makes opinionated choices about how resources are organized (module structure, naming, state layout) but is intentionally designed to be extensible. Teams are encouraged to adapt the Terraform modules, configuration schema, and workflow structure to fit their own conventions.

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
- **CI/CD ready**: Ships with several GitHub Actions workflows covering plan-on-PR, tag-triggered releases, and pipeline refresh operations. Use them as-is or adapt to your own CI platform

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

## Documentation

| Guide | Description |
|-------|-------------|
| [Installation](docs/installation.md) | Clone, configure, authenticate, set up a Terraform backend, and deploy |
| [GitHub Actions CI/CD Setup](docs/cicd-setup.md) | Ready-to-use workflows for plan-on-PR, tag-triggered releases, and pipeline refresh — self-hosted runner setup, secrets, and variables reference |
| [YAML Configuration Reference](docs/yaml-configuration.md) | All configuration options explained with examples |

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
