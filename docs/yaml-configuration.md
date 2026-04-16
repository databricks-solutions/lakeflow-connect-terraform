# YAML Configuration Reference

See `config/examples/` for complete example configurations ([MySQL](../config/examples/mysql.yml), [Oracle](../config/examples/oracle.yml), [PostgreSQL CDC](../config/examples/postgresql.yml), [PostgreSQL QBC](../config/examples/postgresql_qbc.yml), [SQL Server](../config/examples/sqlserver.yml)). The configuration is fully YAML-driven with the following main sections:

## Connector Type

```yaml
connector_type: CDC   # CDC (default) or QBC
```

Two connector modes are supported:

- **CDC** (Change Data Capture, default): streams database changes in near-real-time via a gateway pipeline. Requires `gateway_pipeline_cluster_config` and — for PostgreSQL — a replication slot and publication per database.
- **QBC** (Query-Based Connector): polls the source using SQL queries for incremental sync. Uses serverless compute; no gateway pipeline or cluster configuration needed. Requires explicit table lists with a `cursor_column` per table.

## Connection

```yaml
connection:
  name: "my_uc_connection"       # Name of the existing Unity Catalog connection
  source_type: "POSTGRESQL"      # POSTGRESQL, SQLSERVER, MYSQL, ORACLE

# Oracle only: required when source_type is ORACLE (CDB name for gateway)
# connection_parameters:
#   source_catalog: "ORCLCDB"
```

## Unity Catalog Configuration

```yaml
unity_catalog:
  global_uc_catalog: "my_catalog"      # Required: Default catalog for ingestion pipelines
  staging_uc_catalog: "staging_cat"    # Optional: Catalog for gateway staging (defaults to global_uc_catalog)
  staging_schema: "lf_staging"         # Optional: Schema for gateway staging (defaults to {app_name}_lf_staging)
```

- `global_uc_catalog`: Default catalog where ingestion pipeline tables land (required)
- `staging_uc_catalog`: Catalog for gateway pipeline staging assets (optional, defaults to `global_uc_catalog`)
- `staging_schema`: Schema name for gateway staging assets (optional, defaults to `{app_name}_lf_staging`)

## Databases

```yaml
databases:
  - name: my_database
    # Optional: Override global catalog for this database
    uc_catalog: "custom_catalog"

    # Optional: Customize schema names in Unity Catalog
    schema_prefix: "dev_"      # Results in: dev_<schema_name>
    schema_suffix: "_raw"      # Results in: <schema_name>_raw

    # PostgreSQL only: Replication configuration (required per database)
    replication_slot: "dbx_slot_mydb"
    publication: "dbx_pub_mydb"

    schemas:
      - name: public
        use_schema_ingestion: true   # Ingest all tables automatically
      - name: app_schema
        use_schema_ingestion: false  # Ingest only the tables listed below
        tables:
          - source_table: users
          - source_table: orders
          # Optional per-table destination overrides:
          - source_table: orders_archive
            destination_table: orders_archive_v2  # Optional: rename at destination
            destination_catalog: other_catalog    # Optional: override catalog
            destination_schema: other_schema      # Optional: override schema
```

- `uc_catalog`: Per-database catalog override (optional, falls back to `global_uc_catalog`)
- `schema_prefix` / `schema_suffix`: Customize destination schema names in Unity Catalog (optional). Example: source schema `CLIENT_MANAGEMENT` with prefix `orapdb1_` lands as `orapdb1_client_management`.
- `replication_slot` / `publication`: PostgreSQL-only, required per database
- `use_schema_ingestion: true`: Automatically ingest all tables in the schema; the `tables` list is ignored
- `use_schema_ingestion: false`: Ingest only the explicitly listed tables
- **Per-table destination overrides**: For table-level ingestion, each table can optionally specify `destination_table`, `destination_catalog`, and `destination_schema`. When set, they override the pipeline defaults. All referenced catalogs and schemas are validated against Unity Catalog at deploy time.

### MySQL note

MySQL has no schema level (the hierarchy is server → database → tables). In the YAML, list each database and under `schemas` use a placeholder name (e.g. `"<not applicable in MySQL>"`) and list tables by their full MySQL table name. Set `connection.source_type: "MYSQL"`. If `use_schema_ingestion: true` is set, it is ignored for MySQL and ingestion uses the `tables` list; the Pydantic validator prints an informational message when this is encountered. See `config/examples/mysql.yml` for a complete example.

## QBC — Query-Based Connector

When `connector_type: QBC`, replace the CDC-specific sections (`gateway_pipeline_cluster_config`, `gateway_validation`) with the optional `qbc` defaults block:

```yaml
connector_type: QBC

qbc:
  default_cursor_column: "updated_at"   # Column used for incremental reads (required unless set per-table)
  default_scd_type: "SCD_TYPE_1"        # SCD_TYPE_1, SCD_TYPE_2, or APPEND_ONLY (default: SCD_TYPE_1)
```

Tables must be listed explicitly (`use_schema_ingestion: false`). Each table inherits the QBC defaults but can override them:

```yaml
databases:
  - name: my_database
    schemas:
      - name: my_schema
        use_schema_ingestion: false   # required for QBC
        tables:
          - source_table: orders          # uses default_cursor_column and default_scd_type
          - source_table: customers
            cursor_column: "modified_ts"  # per-table cursor override
            scd_type: "SCD_TYPE_2"        # per-table SCD override
          - source_table: events
            scd_type: "APPEND_ONLY"
            deletion_condition: "is_deleted = true"   # optional: marks logically deleted rows
```

QBC fields:

| Field | Scope | Required | Description |
|-------|-------|----------|-------------|
| `qbc.default_cursor_column` | global | if not set per-table | Column used for incremental reads (e.g. `updated_at`) |
| `qbc.default_scd_type` | global | no (default: `SCD_TYPE_1`) | Default SCD merge strategy |
| `tables[].cursor_column` | per-table | if no global default | Overrides `default_cursor_column` for this table |
| `tables[].scd_type` | per-table | no | Overrides `default_scd_type` for this table |
| `tables[].deletion_condition` | per-table | no | SQL expression identifying soft-deleted rows |

**SCD type reference:**
- `SCD_TYPE_1`: Upsert — overwrite existing rows in place (default)
- `SCD_TYPE_2`: Track full row history with effective-date columns
- `APPEND_ONLY`: Insert every incoming row without deduplication or merging

**PostgreSQL note for QBC:** `replication_slot` and `publication` are **not** needed — QBC connects via the Unity Catalog connection, not the CDC replication path.

See `config/examples/postgresql_qbc.yml` for a complete example.

## Event Logs

```yaml
event_log:
  to_table: true  # Set to false to disable event log table creation
```

When `to_table: true`, pipeline event logs are materialized to Delta tables:
- Gateway pipeline logs → staging schema (e.g. `{app_name}_lf_staging`)
- Ingestion pipeline logs → their respective landing schemas

## Job Orchestration

```yaml
job:
  common_job_for_all_pipelines: false
  common_schedule:
    quartz_cron_expression: "0 */30 * * * ?"   # Applies only when common_job_for_all_pipelines is true
    timezone_id: "UTC"

  # Per-database schedules (when common_job_for_all_pipelines is false)
  per_database_schedules:
    - name: "frequent_sync"
      applies_to: ["db1", "db2"]
      schedule:
        quartz_cron_expression: "0 */15 * * * ?"
        timezone_id: "UTC"
    - name: "hourly_sync"
      applies_to: ["db3"]
      schedule:
        quartz_cron_expression: "0 0 * * * ?"
        timezone_id: "UTC"
```

Two scheduling modes:

1. **Common job** (`common_job_for_all_pipelines: true`): A single Databricks Job runs all ingestion pipelines on the same schedule defined in `common_schedule`.
2. **Per-database scheduling** (`common_job_for_all_pipelines: false`): Separate Databricks Jobs are created per schedule group. Multiple databases can share a schedule by listing them in `applies_to`. This allows different databases to sync at different frequencies.

All cron expressions use **Quartz syntax** and are validated by the Pydantic validator before deployment.

## Gateway Pipeline Cluster Configuration

```yaml
gateway_pipeline_cluster_config:
  label: "default"
  node_type_id: "Standard_E4d_v4"   # Azure VM SKU (or equivalent for your cloud)
  autoscale:
    min_workers: 0
    max_workers: 0
    mode: ENHANCED
  apply_policy_default_values: false
  enable_local_disk_encryption: false
  custom_tags: {}
  spark_conf: {}
  spark_env_vars: {}
  ssh_public_keys: []
```

The cluster policy applied to this cluster is specified separately:

```yaml
gateway_pipeline_cluster_policy_name: my_cluster_policy
```

## Gateway Validation

```yaml
gateway_validation:
  enabled: true                # Set to false to skip validation entirely
  timeout_minutes: 30
  check_interval_seconds: 15
```

After the gateway pipeline is created or updated, a validation script polls the pipeline status before downstream ingestion pipeline resources are created or updated. These settings control how long to wait and how frequently to poll.

- `enabled`: When `true` (default), validation runs and orchestration jobs are not created or updated until the gateway is confirmed running. Set to `false` to skip this step; orchestration jobs deployment proceed immediately after the gateway and ingestion pipeline resources are applied. Useful when pipelines are already actively running and a validate-only pipeline run triggered by Terraform would conflict with ongoing ingestion.

  > **Note:** On first-ever deployment with `enabled: false`, there is a risk that ingestion jobs fire before the gateway is fully up, depending on how soon the job schedule triggers. The first run may fail, but subsequent runs should succeed once the gateway is running normally.

- `timeout_minutes`: How long to wait for the gateway to reach a running state before failing (minimum 15).
- `check_interval_seconds`: How frequently to poll the pipeline status (minimum 5).
