# Configuration Examples

This directory contains example YAML configurations for different database types supported by Lakeflow Connect.

## Available Examples

### `postgresql.yml`
Complete example configuration for PostgreSQL CDC ingestion, including:
- PostgreSQL replication slot and publication configuration
- Multiple databases with different catalogs and schema naming patterns
- Per-database scheduling for flexible sync frequencies
- Event log table materialization

### `sqlserver.yml`
Complete example configuration for SQL Server CDC ingestion, including:
- SQL Server connection setup
- Schema and table selection patterns
- Per-database scheduling options
- Event log configuration

## How to Use These Examples

1. **Copy an example as your starting point:**
   ```bash
   # For PostgreSQL
   cp config/examples/postgresql.yml config/lakeflow_<your_env>.yml
   
   # For SQL Server
   cp config/examples/sqlserver.yml config/lakeflow_<your_env>.yml
   ```

2. **Customize for your environment:**
   - Update `unity_catalog` section with your catalog and schema names
   - Update `connection.name` to match your Unity Catalog connection
   - Configure your source databases, schemas, and tables
   - Adjust cluster configuration and scheduling as needed
   - For PostgreSQL: Ensure replication slots and publications are created in your source database

3. **Deploy using Terraform:**
   ```bash
   cd infra
   terraform plan --var yaml_config_path=../config/lakeflow_<your_env>.yml
   terraform apply --var yaml_config_path=../config/lakeflow_<your_env>.yml
   ```

## Key Configuration Sections

All examples include the following configurable sections:

- **`unity_catalog`**: Where data lands in Unity Catalog
- **`connection`**: Unity Catalog connection details
- **`databases`**: Source databases, schemas, and tables to ingest
- **`gateway_pipeline_cluster_config`**: Compute configuration for the gateway
- **`event_log`**: Pipeline monitoring and observability
- **`job`**: Orchestration and scheduling

## Security Note

⚠️ **Never commit actual credentials or production configurations to version control.**

- These examples use placeholder names and should be customized for your environment
- Consider using environment variables or secret management for sensitive values
- Add your actual configuration files to `.gitignore`

## Need Help?

Refer to the main [README.md](../../README.md) for detailed documentation on:
- Prerequisites and setup steps
- Complete configuration reference
- Deployment instructions
- Troubleshooting
