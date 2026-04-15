"""
Trigger full refresh on Databricks Lakeflow Connect ingestion pipelines.

Supports two modes:
  1. Full pipeline refresh  - refreshes ALL tables in a pipeline
  2. Selective table refresh - refreshes only specified tables in a pipeline

Usage:
  # Full pipeline refresh
  python tools/trigger_full_refresh.py --pipeline-id <id> --mode full

  # Selective table refresh (specific tables)
  python tools/trigger_full_refresh.py --pipeline-id <id> --mode tables \
      --tables "catalog.schema.table1,catalog.schema.table2"

  # Dry run (validate inputs without triggering refresh)
  python tools/trigger_full_refresh.py --pipeline-id <id> --mode full --dry-run

Requires:
  - DATABRICKS_HOST: Databricks workspace URL
  - ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_TENANT_ID: Azure service principal credentials
    (the Databricks SDK picks these up automatically for azure-client-secret auth)
"""

import argparse
import json
import os
import sys
import time

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    print("ERROR: databricks-sdk is required. Install with: pip install databricks-sdk")
    sys.exit(1)


def get_pipeline_info(client: WorkspaceClient, pipeline_id: str) -> dict:
    """Retrieve pipeline metadata for validation and display."""
    pipeline = client.pipelines.get(pipeline_id=pipeline_id)
    return {
        "pipeline_id": pipeline.pipeline_id,
        "name": pipeline.name,
        "state": pipeline.state.value if pipeline.state else "UNKNOWN",
    }


def resolve_table_names(client: WorkspaceClient, pipeline_id: str, tables: list[str]) -> list[str]:
    """
    Resolve user-supplied table names to the EXACT names used in the pipeline's
    ingestion_definition (required by full_refresh_selection — case-sensitive).

    Accepts schema.table or catalog.schema.table (matched case-insensitively
    against the pipeline spec; the pipeline's own casing is always used in output).
    """
    pipeline = client.pipelines.get(pipeline_id=pipeline_id)

    # Build a map: lowercase(catalog.schema.table) -> exact(catalog.schema.table)
    # from the pipeline's ingestion_definition.objects
    pipeline_tables: dict[str, str] = {}
    if (pipeline.spec
            and pipeline.spec.ingestion_definition
            and pipeline.spec.ingestion_definition.objects):
        for obj in pipeline.spec.ingestion_definition.objects:
            if obj.table:
                t = obj.table
                exact = f"{t.destination_catalog}.{t.destination_schema}.{t.destination_table}"
                pipeline_tables[exact.lower()] = exact

    if not pipeline_tables:
        print("ERROR: Pipeline has no ingestion tables defined in its spec.")
        sys.exit(1)

    print(f"Pipeline tables: {list(pipeline_tables.values())}")

    resolved = []
    for table in tables:
        parts = table.strip().split(".")
        if len(parts) == 2:
            # Match schema.table case-insensitively against the last two parts
            schema_table = table.strip().lower()
            matched = next(
                (exact for lc, exact in pipeline_tables.items()
                 if ".".join(lc.split(".")[1:]) == schema_table),
                None,
            )
        elif len(parts) == 3:
            matched = pipeline_tables.get(table.strip().lower())
        else:
            print(f"ERROR: Table '{table}' must be schema.table or catalog.schema.table")
            sys.exit(1)

        if matched is None:
            print(f"ERROR: Table '{table}' not found in pipeline ingestion definition.")
            print(f"  Available: {list(pipeline_tables.values())}")
            sys.exit(1)

        resolved.append(matched)

    return resolved


def trigger_full_refresh(
    client: WorkspaceClient,
    pipeline_id: str,
    mode: str,
    tables: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Trigger a full refresh on a Databricks pipeline.

    Args:
        client: Databricks WorkspaceClient
        pipeline_id: The pipeline ID to refresh
        mode: 'full' for entire pipeline, 'tables' for specific tables
        tables: List of fully-qualified table names (required when mode='tables')
        dry_run: If True, validate inputs but do not trigger the refresh

    Returns:
        dict with update_id and status
    """
    # Validate pipeline exists and is in a refreshable state
    info = get_pipeline_info(client, pipeline_id)
    print(f"Pipeline: {info['name']} ({info['pipeline_id']})")
    print(f"Current state: {info['state']}")

    if dry_run:
        print("\n[DRY RUN] Would trigger the following refresh:")
        print(f"  Mode: {mode}")
        if mode == "tables" and tables:
            print(f"  Tables: {', '.join(tables)}")
        print("\n[DRY RUN] No changes made.")
        return {"status": "dry_run", "pipeline_id": pipeline_id}

    if mode == "full":
        print("\nTriggering FULL REFRESH on entire pipeline...")
        update = client.pipelines.start_update(
            pipeline_id=pipeline_id,
            full_refresh=True,
        )
    elif mode == "tables":
        if not tables:
            print("ERROR: --tables is required when mode is 'tables'")
            sys.exit(1)
        print(f"\nTriggering FULL REFRESH on specific tables:")
        for t in tables:
            print(f"  - {t}")
        update = client.pipelines.start_update(
            pipeline_id=pipeline_id,
            full_refresh_selection=tables,
        )
    else:
        print(f"ERROR: Unknown mode '{mode}'. Use 'full' or 'tables'.")
        sys.exit(1)

    update_id = update.update_id
    print(f"\nUpdate triggered successfully!")
    print(f"Update ID: {update_id}")

    return {
        "status": "triggered",
        "pipeline_id": pipeline_id,
        "update_id": update_id,
        "mode": mode,
        "tables": tables if mode == "tables" else "ALL",
    }


def wait_for_completion(
    client: WorkspaceClient,
    pipeline_id: str,
    update_id: str,
    timeout_minutes: int = 60,
    check_interval_seconds: int = 30,
) -> str:
    """
    Wait for a pipeline update to complete.

    Returns the final state: COMPLETED, FAILED, CANCELED, etc.
    """
    print(f"\nWaiting for update {update_id} to complete (timeout: {timeout_minutes}m)...")
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            print(f"ERROR: Timeout after {timeout_minutes} minutes")
            return "TIMEOUT"

        update_info = client.pipelines.get_update(
            pipeline_id=pipeline_id,
            update_id=update_id,
        )
        state = update_info.update.state.value if update_info.update.state else "UNKNOWN"
        print(f"  [{int(elapsed)}s] State: {state}")

        if state in ("COMPLETED", "FAILED", "CANCELED"):
            return state

        time.sleep(check_interval_seconds)


def resolve_pipeline_ids_from_config(config_path: str, target: str) -> list[str]:
    """
    Resolve pipeline pair keys from the YAML config file.

    The target can be:
      - A database name (e.g., 'wealth_mgmt_one') -> returns all schema pairs
      - A database.schema pair (e.g., 'wealth_mgmt_one.client_management')

    Note: This returns pair_keys, not pipeline IDs. The caller must map these
    to actual pipeline IDs using Terraform output or state.
    """
    import yaml

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    pair_keys = []
    for db in cfg.get("databases", []):
        for schema in db.get("schemas", []):
            pair_key = f"{db['name']}_{schema['name']}"
            if target == db["name"] or target == f"{db['name']}.{schema['name']}":
                pair_keys.append(pair_key)

    if not pair_keys:
        print(f"WARNING: No matching pipelines found for target '{target}'")

    return pair_keys


def main():
    parser = argparse.ArgumentParser(
        description="Trigger full refresh on Databricks Lakeflow Connect pipelines"
    )
    parser.add_argument(
        "--pipeline-id",
        required=True,
        help="Databricks pipeline ID to refresh",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["full", "tables"],
        help="Refresh mode: 'full' for entire pipeline, 'tables' for specific tables",
    )
    parser.add_argument(
        "--tables",
        help="Comma-separated list of fully-qualified table names (catalog.schema.table)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs without triggering the refresh",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the refresh to complete",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=60,
        help="Timeout in minutes when --wait is used (default: 60)",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=30,
        help="Check interval in seconds when --wait is used (default: 30)",
    )

    args = parser.parse_args()

    # Validate environment
    if not os.environ.get("DATABRICKS_HOST"):
        print("ERROR: DATABRICKS_HOST environment variable is required")
        sys.exit(1)

    # Initialize client
    client = WorkspaceClient()

    # Parse and resolve tables if provided
    tables = None
    if args.tables:
        tables = resolve_table_names(client, args.pipeline_id, args.tables.split(","))

    if args.mode == "tables" and not tables:
        print("ERROR: --tables is required when --mode is 'tables'")
        sys.exit(1)

    # Trigger the refresh
    result = trigger_full_refresh(
        client=client,
        pipeline_id=args.pipeline_id,
        mode=args.mode,
        tables=tables,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        sys.exit(0)

    # Optionally wait for completion
    if args.wait and result.get("update_id"):
        final_state = wait_for_completion(
            client=client,
            pipeline_id=args.pipeline_id,
            update_id=result["update_id"],
            timeout_minutes=args.timeout_minutes,
            check_interval_seconds=args.check_interval,
        )
        print(f"\nFinal state: {final_state}")
        if final_state != "COMPLETED":
            sys.exit(1)

    # Output result as JSON for CI/CD consumption
    print(f"\n--- Result ---")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
