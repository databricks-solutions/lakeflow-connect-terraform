"""
Pydantic-based YAML configuration validator for Lakeflow Connect Terraform.

This validator provides type-safe validation with comprehensive error messages
for all configuration parameters.
"""

import re
import sys
from pathlib import Path
from typing import Literal, Optional

import yaml
from croniter import croniter
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    ValidationError,
)


# ============================================
# Pydantic Models
# ============================================


class ScheduleConfig(BaseModel):
    """Schedule configuration with cron expression validation."""
    
    quartz_cron_expression: str = Field(
        ...,
        description="Quartz cron expression for scheduling"
    )
    timezone_id: str = Field(
        ...,
        description="Timezone ID (e.g., 'UTC', 'America/New_York')"
    )
    
    @field_validator("quartz_cron_expression")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate that the cron expression is valid."""
        if not v or not v.strip():
            raise ValueError("Cron expression cannot be empty")
        
        # Quartz cron has 6 or 7 fields (seconds, minutes, hours, day of month, month, day of week, [year])
        parts = v.strip().split()
        if len(parts) < 6 or len(parts) > 7:
            raise ValueError(
                f"Quartz cron expression must have 6 or 7 fields, got {len(parts)}. "
                f"Format: 'second minute hour day month weekday [year]'"
            )
        
        # Try to validate with croniter (convert Quartz to standard cron for validation)
        # Standard cron is 5 fields, Quartz adds seconds at start
        try:
            # Remove seconds field for croniter validation (it uses standard cron)
            standard_cron = " ".join(parts[1:6])  # minute hour day month weekday
            croniter(standard_cron)
        except Exception as e:
            raise ValueError(f"Invalid cron expression: {e}")
        
        return v
    
    @field_validator("timezone_id")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone ID is non-empty."""
        if not v or not v.strip():
            raise ValueError("Timezone ID cannot be empty")
        return v


class PerDatabaseSchedule(BaseModel):
    """Per-database schedule configuration."""
    
    name: str = Field(
        ...,
        description="Name of this schedule group"
    )
    applies_to: list[str] = Field(
        ...,
        description="List of database names this schedule applies to"
    )
    schedule: ScheduleConfig
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate schedule name is non-empty."""
        if not v or not v.strip():
            raise ValueError("Schedule name cannot be empty")
        return v
    
    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, v: list[str]) -> list[str]:
        """Validate applies_to is a non-empty list."""
        if not isinstance(v, list):
            raise ValueError("applies_to must be a list")
        # Empty list is allowed - will be caught by cross-validation
        return v


class JobConfig(BaseModel):
    """Job orchestration configuration."""
    
    common_job_for_all_pipelines: bool = Field(
        ...,
        description="Whether to use a single job for all pipelines"
    )
    common_schedule: ScheduleConfig = Field(
        ...,
        description="Default schedule for all pipelines"
    )
    per_database_schedules: Optional[list[PerDatabaseSchedule]] = Field(
        default=None,
        description="Per-database schedules (required when common_job_for_all_pipelines is false)"
    )
    
    @model_validator(mode="after")
    def validate_per_database_schedules(self):
        """Validate that per_database_schedules is provided when needed."""
        if not self.common_job_for_all_pipelines:
            if not self.per_database_schedules:
                raise ValueError(
                    "job.per_database_schedules is required when "
                    "common_job_for_all_pipelines is false"
                )
        return self


class TableConfig(BaseModel):
    """Table selection configuration."""

    source_table: str = Field(
        ...,
        description="Source table name"
    )
    destination_table: Optional[str] = Field(
        default=None,
        description="Destination table name in Unity Catalog (defaults to source_table)"
    )
    destination_catalog: Optional[str] = Field(
        default=None,
        description="Override destination catalog for this table (defaults to schema/database-level catalog)"
    )
    destination_schema: Optional[str] = Field(
        default=None,
        description="Override destination schema for this table (defaults to schema/database-level schema)"
    )
    # QBC-specific fields (optional; may also be set via qbc.default_cursor_column / qbc.default_scd_type)
    cursor_column: Optional[str] = Field(
        default=None,
        description="QBC: column used as cursor for incremental sync (overrides qbc.default_cursor_column)"
    )
    scd_type: Optional[str] = Field(
        default=None,
        description="QBC: SCD strategy — SCD_TYPE_1, SCD_TYPE_2, or APPEND_ONLY (overrides qbc.default_scd_type)"
    )
    deletion_condition: Optional[str] = Field(
        default=None,
        description="QBC: SQL expression to identify soft-deleted rows (optional)"
    )

    @field_validator("source_table")
    @classmethod
    def validate_table_name(cls, v: str) -> str:
        """Validate table name is non-empty."""
        if not v or not v.strip():
            raise ValueError("Table name cannot be empty")
        return v

    @field_validator("scd_type")
    @classmethod
    def validate_scd_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate scd_type is one of the allowed values."""
        if v is not None:
            allowed = {"SCD_TYPE_1", "SCD_TYPE_2", "APPEND_ONLY"}
            if v not in allowed:
                raise ValueError(
                    f"scd_type must be one of {sorted(allowed)}, got: {v!r}"
                )
        return v


class SchemaConfig(BaseModel):
    """Schema configuration for ingestion."""
    
    name: str = Field(
        ...,
        description="Schema name"
    )
    use_schema_ingestion: bool = Field(
        ...,
        description="Whether to ingest all tables in the schema"
    )
    tables: Optional[list[TableConfig]] = Field(
        default=None,
        description="List of tables to ingest (required when use_schema_ingestion is false)"
    )
    
    @field_validator("name")
    @classmethod
    def validate_schema_name(cls, v: str) -> str:
        """Validate schema name is non-empty."""
        if not v or not v.strip():
            raise ValueError("Schema name cannot be empty")
        return v
    
    @model_validator(mode="after")
    def validate_tables_when_needed(self):
        """Validate that tables are provided when use_schema_ingestion is false."""
        if not self.use_schema_ingestion:
            if not self.tables or len(self.tables) == 0:
                raise ValueError(
                    f"Schema '{self.name}': tables list is required and must be non-empty "
                    f"when use_schema_ingestion is false"
                )
        return self


class DatabaseConfig(BaseModel):
    """Database configuration."""
    
    model_config = ConfigDict(extra="forbid")  # Will catch unknown fields
    
    name: str = Field(
        ...,
        description="Database name"
    )
    uc_catalog: Optional[str] = Field(
        default=None,
        description="Override Unity Catalog name for this database"
    )
    schema_prefix: Optional[str] = Field(
        default=None,
        description="Prefix for schema names in Unity Catalog"
    )
    schema_suffix: Optional[str] = Field(
        default=None,
        description="Suffix for schema names in Unity Catalog"
    )
    replication_slot: Optional[str] = Field(
        default=None,
        description="PostgreSQL replication slot name (PostgreSQL only)"
    )
    publication: Optional[str] = Field(
        default=None,
        description="PostgreSQL publication name (PostgreSQL only)"
    )
    schemas: list[SchemaConfig] = Field(
        ...,
        description="List of schemas to ingest from this database"
    )
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate database name is non-empty."""
        if not v or not v.strip():
            raise ValueError("Database name cannot be empty")
        return v
    
    @field_validator("schema_prefix", "schema_suffix")
    @classmethod
    def validate_schema_affix(cls, v: Optional[str]) -> Optional[str]:
        """Validate schema prefix/suffix doesn't contain invalid characters."""
        if v is not None:
            # Unity Catalog schema names: alphanumeric, underscore, hyphen
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError(
                    f"Schema prefix/suffix '{v}' contains invalid characters. "
                    f"Only alphanumeric, underscore, and hyphen are allowed."
                )
        return v
    
    @field_validator("schemas")
    @classmethod
    def validate_schemas_non_empty(cls, v: list[SchemaConfig]) -> list[SchemaConfig]:
        """Validate that schemas list is non-empty."""
        if not v or len(v) == 0:
            raise ValueError("Database must have at least one schema")
        return v


class UnityCatalogConfig(BaseModel):
    """Unity Catalog configuration."""
    
    global_uc_catalog: Optional[str] = Field(
        default=None,
        description="Default Unity Catalog for all ingestion pipelines"
    )
    staging_uc_catalog: Optional[str] = Field(
        default=None,
        description="Unity Catalog for gateway staging assets"
    )
    staging_schema: Optional[str] = Field(
        default=None,
        description="Schema name for gateway staging assets"
    )
    
    @field_validator("staging_schema")
    @classmethod
    def validate_staging_schema(cls, v: Optional[str]) -> Optional[str]:
        """Validate staging schema name if provided."""
        if v is not None and (not v or not v.strip()):
            raise ValueError("staging_schema cannot be empty string")
        return v


class OracleConnectionParameters(BaseModel):
    """Oracle-specific connection parameters (e.g. CDB name for gateway)."""

    source_catalog: str = Field(
        ...,
        description="Oracle CDB (container database) name, e.g. ORCLCDB"
    )

    @field_validator("source_catalog")
    @classmethod
    def validate_source_catalog(cls, v: str) -> str:
        """Validate source_catalog is non-empty."""
        if not v or not v.strip():
            raise ValueError("connection_parameters.source_catalog cannot be empty for Oracle")
        return v


class ConnectionConfig(BaseModel):
    """Database connection configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Unity Catalog connection name"
    )
    source_type: Literal["POSTGRESQL", "SQLSERVER", "MYSQL", "ORACLE"] = Field(
        ...,
        description="Source database type"
    )
    connection_parameters: Optional[OracleConnectionParameters] = Field(
        default=None,
        description="Oracle-only: source_catalog (CDB name). Required when source_type is ORACLE."
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate connection name is non-empty."""
        if not v or not v.strip():
            raise ValueError("Connection name cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_oracle_connection_parameters(self):
        """
        connection_parameters is only valid for Oracle sources.
        Whether it is *required* depends on connector_type (CDC only) — checked in AppConfig.
        """
        if self.source_type != "ORACLE" and self.connection_parameters is not None:
            raise ValueError(
                f"connection.connection_parameters is only valid for Oracle sources, "
                f"but source_type is {self.source_type}"
            )
        return self


class AutoscaleConfig(BaseModel):
    """Autoscale configuration for cluster."""
    
    min_workers: int = Field(..., ge=0)
    max_workers: int = Field(..., ge=0)
    mode: str


class GatewayPipelineClusterConfig(BaseModel):
    """Gateway pipeline cluster configuration."""
    
    label: str
    node_type_id: str
    autoscale: Optional[AutoscaleConfig] = None
    num_workers: Optional[int] = Field(default=None, ge=0)
    apply_policy_default_values: bool
    enable_local_disk_encryption: bool
    custom_tags: Optional[dict] = Field(default_factory=dict)
    spark_conf: Optional[dict] = Field(default_factory=dict)
    spark_env_vars: Optional[dict] = Field(default_factory=dict)
    ssh_public_keys: Optional[list[str]] = Field(default_factory=list)
    
    @model_validator(mode="after")
    def validate_autoscale_or_workers(self):
        """Validate that either autoscale or num_workers is provided."""
        has_autoscale = self.autoscale is not None
        has_num_workers = self.num_workers is not None
        
        if not has_autoscale and not has_num_workers:
            raise ValueError(
                "gateway_pipeline_cluster_config must have either 'autoscale' or 'num_workers'"
            )
        
        return self


class GatewayValidationConfig(BaseModel):
    """Gateway validation configuration."""

    enabled: bool = Field(
        default=True,
        description="Set to false to skip gateway validation entirely (e.g. when pipelines are already running)"
    )
    timeout_minutes: int = Field(default=30, ge=15)
    check_interval_seconds: int = Field(default=15, ge=5)


class QBCConfig(BaseModel):
    """Query-Based Connector defaults applied across all tables."""

    default_cursor_column: Optional[str] = Field(
        default=None,
        description="Default cursor column for incremental sync (overridden per-table)"
    )
    default_scd_type: str = Field(
        default="SCD_TYPE_1",
        description="Default SCD strategy — SCD_TYPE_1, SCD_TYPE_2, or APPEND_ONLY"
    )

    @field_validator("default_scd_type")
    @classmethod
    def validate_default_scd_type(cls, v: str) -> str:
        """Validate default_scd_type is one of the allowed values."""
        allowed = {"SCD_TYPE_1", "SCD_TYPE_2", "APPEND_ONLY"}
        if v not in allowed:
            raise ValueError(
                f"qbc.default_scd_type must be one of {sorted(allowed)}, got: {v!r}"
            )
        return v


class EventLogConfig(BaseModel):
    """Event log configuration."""
    
    to_table: bool = Field(
        ...,
        description="Whether to materialize event logs to Delta tables"
    )
    
    @field_validator("to_table")
    @classmethod
    def validate_to_table(cls, v) -> bool:
        """Validate that to_table is a boolean."""
        if not isinstance(v, bool):
            raise ValueError(
                f"event_log.to_table must be a boolean (true/false), got: {v} ({type(v).__name__})"
            )
        return v


class LakeflowConfig(BaseModel):
    """Root configuration model for Lakeflow Connect."""

    env: str = Field(
        ...,
        description="Environment name (e.g., 'dev', 'prod')"
    )
    app_name: str = Field(
        ...,
        description="Application name"
    )
    connector_type: str = Field(
        default="CDC",
        description="Connector mode: CDC (Change Data Capture) or QBC (Query-Based Connector)"
    )
    unity_catalog: Optional[UnityCatalogConfig] = Field(
        default=None,
        description="Unity Catalog configuration"
    )
    connection: ConnectionConfig
    gateway_pipeline_cluster_policy_name: Optional[str] = Field(
        default=None,
        description="Cluster policy name for gateway pipeline (CDC only)"
    )
    databases: list[DatabaseConfig] = Field(
        ...,
        min_length=1,
        description="List of source databases"
    )
    # CDC-only: required when connector_type is CDC
    gateway_pipeline_cluster_config: Optional[GatewayPipelineClusterConfig] = Field(
        default=None,
        description="Gateway pipeline cluster configuration (CDC only)"
    )
    gateway_validation: Optional[GatewayValidationConfig] = Field(
        default=None,
        description="Gateway validation settings (CDC only)"
    )
    event_log: Optional[EventLogConfig] = Field(
        default=None,
        description="Event log configuration"
    )
    job: JobConfig
    # QBC-only: optional defaults applied across all tables
    qbc: Optional[QBCConfig] = Field(
        default=None,
        description="Query-Based Connector defaults (QBC only)"
    )
    
    @field_validator("env", "app_name")
    @classmethod
    def validate_non_empty_string(cls, v: str) -> str:
        """Validate that string fields are non-empty."""
        if not v or not v.strip():
            raise ValueError("Value must be a non-empty string")
        return v

    @field_validator("connector_type")
    @classmethod
    def validate_connector_type(cls, v: str) -> str:
        """Validate connector_type is CDC or QBC."""
        normalised = v.upper()
        if normalised not in {"CDC", "QBC"}:
            raise ValueError(
                f"connector_type must be 'CDC' or 'QBC', got: {v!r}"
            )
        return normalised

    @model_validator(mode="after")
    def validate_cdc_specific_fields(self):
        """For CDC, gateway_pipeline_cluster_config and Oracle connection_parameters are required."""
        if self.connector_type == "CDC":
            if self.gateway_pipeline_cluster_config is None:
                raise ValueError(
                    "gateway_pipeline_cluster_config is required for CDC connector type"
                )
            if self.connection.source_type == "ORACLE" and self.connection.connection_parameters is None:
                raise ValueError(
                    "connection.connection_parameters is required for Oracle CDC "
                    "(e.g. connection_parameters.source_catalog for the CDB name)"
                )
        return self

    @model_validator(mode="after")
    def validate_unity_catalog_configuration(self):
        """
        Validate Unity Catalog configuration logic.

        CDC:
          - global_uc_catalog set → OK
          - global_uc_catalog absent → staging_uc_catalog required AND every database must have uc_catalog

        QBC:
          - global_uc_catalog set → OK (used as fallback for any database without uc_catalog)
          - global_uc_catalog absent / unity_catalog omitted → every database must have uc_catalog
            (the unity_catalog section can be omitted entirely in this case)
        """
        uc_config = self.unity_catalog
        is_qbc = self.connector_type == "QBC"

        has_global = uc_config is not None and uc_config.global_uc_catalog is not None
        has_staging = uc_config is not None and uc_config.staging_uc_catalog is not None

        if not has_global:
            # CDC requires the unity_catalog block and a staging catalog
            if not is_qbc:
                if uc_config is None:
                    raise ValueError(
                        "unity_catalog configuration is required for CDC. "
                        "Provide global_uc_catalog, or staging_uc_catalog + per-database uc_catalog."
                    )
                if not has_staging:
                    raise ValueError(
                        "unity_catalog.staging_uc_catalog is required for CDC "
                        "when global_uc_catalog is not provided"
                    )

            # Both CDC and QBC: without a global fallback every database must name its own catalog
            databases_without_catalog = [
                db.name for db in self.databases if db.uc_catalog is None
            ]
            if databases_without_catalog:
                raise ValueError(
                    "When unity_catalog.global_uc_catalog is not provided, every database must "
                    "specify uc_catalog. Missing for: "
                    + ", ".join(databases_without_catalog)
                )

        return self
    
    @model_validator(mode="after")
    def validate_postgresql_configuration(self):
        """
        Validate PostgreSQL-specific configuration:
        - CDC + POSTGRESQL: databases MUST have replication_slot and publication
        - QBC + POSTGRESQL: replication_slot and publication are NOT required
        - Non-POSTGRESQL: these fields should NOT be present
        """
        source_type = self.connection.source_type
        is_qbc = self.connector_type == "QBC"

        for db in self.databases:
            has_replication = db.replication_slot is not None
            has_publication = db.publication is not None

            if source_type == "POSTGRESQL":
                if is_qbc:
                    # QBC uses the UC connection — no replication slot / publication needed
                    if has_replication:
                        raise ValueError(
                            f"Database '{db.name}': replication_slot is not used for QBC "
                            f"PostgreSQL sources (QBC connects via Unity Catalog)"
                        )
                    if has_publication:
                        raise ValueError(
                            f"Database '{db.name}': publication is not used for QBC "
                            f"PostgreSQL sources (QBC connects via Unity Catalog)"
                        )
                else:
                    # CDC + PostgreSQL requires both fields
                    if not has_replication:
                        raise ValueError(
                            f"Database '{db.name}': replication_slot is required for PostgreSQL CDC"
                        )
                    if not has_publication:
                        raise ValueError(
                            f"Database '{db.name}': publication is required for PostgreSQL CDC"
                        )
            else:
                # Non-PostgreSQL should not have these fields
                if has_replication:
                    raise ValueError(
                        f"Database '{db.name}': replication_slot is only valid for PostgreSQL sources, "
                        f"but source_type is {source_type}"
                    )
                if has_publication:
                    raise ValueError(
                        f"Database '{db.name}': publication is only valid for PostgreSQL sources, "
                        f"but source_type is {source_type}"
                    )

        return self
    
    @model_validator(mode="after")
    def validate_mysql_schema_ingestion_warning(self):
        """
        For MySQL: use_schema_ingestion=true does not apply (no schema level).
        Emit a warning when set; Terraform will ignore it and use table-level ingestion.
        """
        if self.connection.source_type != "MYSQL":
            return self
        for db in self.databases:
            for schema in db.schemas:
                if schema.use_schema_ingestion:
                    print(
                        "INFO: 'use_schema_ingestion' setting as True does not apply for MySQL. "
                        "Ignoring and ingesting based on tables passed.",
                        file=sys.stderr,
                    )
                    return self  # One warning is enough
        return self

    @model_validator(mode="after")
    def validate_qbc_configuration(self):
        """
        Validate QBC-specific configuration:
        - Every table must have a resolved cursor_column (per-table or via qbc.default_cursor_column).
        - use_schema_ingestion must be false for every schema (QBC only supports explicit table lists).
        """
        if self.connector_type != "QBC":
            return self

        default_cursor = self.qbc.default_cursor_column if self.qbc else None

        for db in self.databases:
            for schema in db.schemas:
                if schema.use_schema_ingestion:
                    raise ValueError(
                        f"Database '{db.name}', schema '{schema.name}': "
                        f"use_schema_ingestion must be false for QBC — "
                        f"provide an explicit tables list with cursor_column"
                    )
                tables = schema.tables or []
                for table in tables:
                    resolved_cursor = table.cursor_column or default_cursor
                    if not resolved_cursor:
                        raise ValueError(
                            f"Database '{db.name}', schema '{schema.name}', "
                            f"table '{table.source_table}': cursor_column is required for QBC. "
                            f"Set it on the table or via qbc.default_cursor_column."
                        )

        return self

    @model_validator(mode="after")
    def validate_per_database_schedules(self):
        """
        Validate per-database schedule configuration:
        - Database names in applies_to must exist
        - All databases must be covered by exactly one schedule
        - No duplicate assignments
        """
        if not self.job.common_job_for_all_pipelines:
            if not self.job.per_database_schedules:
                # Already validated by JobConfig, but double-check
                return self
            
            # Get all database names
            db_names = {db.name for db in self.databases}
            
            # Track which databases are covered and by which schedule
            db_to_schedule = {}
            
            for schedule in self.job.per_database_schedules:
                # Check for non-existent databases
                invalid_dbs = set(schedule.applies_to) - db_names
                if invalid_dbs:
                    raise ValueError(
                        f"Schedule '{schedule.name}' references non-existent database(s): "
                        f"{', '.join(sorted(invalid_dbs))}"
                    )
                
                # Check for duplicate assignments
                for db_name in schedule.applies_to:
                    if db_name in db_to_schedule:
                        raise ValueError(
                            f"Database '{db_name}' is assigned to multiple schedules: "
                            f"'{db_to_schedule[db_name]}' and '{schedule.name}'"
                        )
                    db_to_schedule[db_name] = schedule.name
            
            # Check for unscheduled databases
            scheduled_dbs = set(db_to_schedule.keys())
            unscheduled_dbs = db_names - scheduled_dbs
            
            if unscheduled_dbs:
                raise ValueError(
                    f"The following database(s) are not covered by any schedule: "
                    f"{', '.join(sorted(unscheduled_dbs))}. "
                    f"Please add them to the 'applies_to' list of an appropriate schedule."
                )
        
        return self


# ============================================
# Validation Function
# ============================================


def validate_yaml(path: Path) -> int:
    """
    Validate a YAML configuration file using Pydantic models.
    
    Args:
        path: Path to the YAML configuration file
    
    Returns:
        Exit code: 0 (success), 1 (validation error), 2 (file not found), 3 (YAML parse error)
    """
    # Check if file exists
    if not path.exists():
        print(f"FAILED. Config file not found: {path}", file=sys.stderr)
        return 2
    
    # Parse YAML
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"FAILED. YAML parse error: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"FAILED. Error reading file: {e}", file=sys.stderr)
        return 2
    
    # Validate with Pydantic
    try:
        config = LakeflowConfig(**data)
        print("SUCCESS. YAML validation passed!")
        print(f"   - Environment: {config.env}")
        print(f"   - Application: {config.app_name}")
        print(f"   - Connector type: {config.connector_type}")
        print(f"   - Source type: {config.connection.source_type}")
        print(f"   - Databases: {len(config.databases)}")
        print(f"   - Event logs to table: {config.event_log.to_table if config.event_log else 'Not configured'}")
        return 0
    except ValidationError as e:
        print("FAILED. Validation failed:\n", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", str(err))
            print(f"   {loc}: {msg}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"FAILED. Validation failed:\n", file=sys.stderr)
        for line in str(e).split("\n"):
            if line.strip():
                print(f"   {line}", file=sys.stderr)
        return 1


def main() -> None:
    """Main entry point for the validator."""
    if len(sys.argv) < 2:
        print("Usage: python pydantic_validator.py <path-to-yaml-config>", file=sys.stderr)
        print("\nExample:")
        print("  poetry run python tools/pydantic_validator.py config/lakeflow_dev.yml")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    exit_code = validate_yaml(path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
