import sys
from pathlib import Path
import yaml


REQUIRED_TOP_LEVEL_KEYS = [
    "env", 
    "app_name",
    "connection", 
    "databases", 
    "gateway_pipeline_cluster_config", 
    "gateway_validation",
    "job"
]


def validate_yaml(path: Path) -> int:
    if not path.exists():
        print(f"Config not found: {path}", file=sys.stderr)
        return 2
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"YAML parse error: {e}", file=sys.stderr)
        return 3

    errors: list[str] = []

    # Check required top-level keys
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in data:
            errors.append(f"Missing top-level key: {key}")

    # Validate connection configuration
    conn = (data or {}).get("connection", {})
    if conn:        
        if not conn.get("name", {}):
            errors.append("connection.name is required")

    # Validate databases configuration
    databases = (data or {}).get("databases", [])
    if not databases:
        errors.append("databases must contain at least one database")
    else:
        for i, db in enumerate(databases):
            if not isinstance(db, dict):
                errors.append(f"database[{i}] must be an object")
                continue
            
            if "name" not in db:
                errors.append(f"database[{i}].name is required")
            
            schemas = db.get("schemas", [])
            if not schemas:
                errors.append(f"database[{i}].schemas must contain at least one schema")
            elif not isinstance(schemas, list):
                errors.append(f"database[{i}].schemas must be a list")

    # Validate gateway pipeline cluster configuration
    cluster_config = (data or {}).get("gateway_pipeline_cluster_config", {})
    if cluster_config:
        required_cluster_keys = [
            "label", "node_type_id",
            "apply_policy_default_values", "enable_local_disk_encryption"
        ]
        for key in required_cluster_keys:
            if key not in cluster_config:
                errors.append(f"gateway_pipeline_cluster_config.{key} is required")
        
        # Either autoscale or num_workers should be present
        has_autoscale = "autoscale" in cluster_config
        has_num_workers = "num_workers" in cluster_config
        if not has_autoscale and not has_num_workers:
            errors.append(
                "gateway_pipeline_cluster_config must have either 'autoscale' or 'num_workers'"
            )

    # Validate gateway validation configuration
    gateway_validation = (data or {}).get("gateway_validation", {})
    if gateway_validation:
        timeout_minutes = gateway_validation.get("timeout_minutes")
        if timeout_minutes is None:
            errors.append("gateway_validation.timeout_minutes is required")
        elif not isinstance(timeout_minutes, int) or timeout_minutes < 15:
            errors.append("gateway_validation.timeout_minutes must be an integer >= 15")
        
        check_interval = gateway_validation.get("check_interval_seconds")
        if check_interval is None:
            errors.append("gateway_validation.check_interval_seconds is required")
        elif not isinstance(check_interval, int) or check_interval < 5:
            errors.append("gateway_validation.check_interval_seconds must be an integer >= 5")

    # Validate job configuration
    job = (data or {}).get("job", {})
    if job:
        if "common_job_for_all_pipelines" not in job:
            errors.append("job.common_job_for_all_pipelines is required")
        
        common_job_for_all = job.get("common_job_for_all_pipelines", True)
        
        # Validate common_schedule (required regardless of mode)
        common_schedule = job.get("common_schedule")
        if not common_schedule:
            # Try legacy 'schedule' key for backward compatibility
            common_schedule = job.get("schedule")
            if not common_schedule:
                errors.append("job.common_schedule is required")
        
        if common_schedule:
            if "quartz_cron_expression" not in common_schedule:
                errors.append("job.common_schedule.quartz_cron_expression is required")
            if "timezone_id" not in common_schedule:
                errors.append("job.common_schedule.timezone_id is required")
        
        # If per-database scheduling is enabled, validate all databases are covered
        if not common_job_for_all:
            per_db_schedules = job.get("per_database_schedules", [])
            
            if not per_db_schedules:
                errors.append(
                    "job.per_database_schedules is required when "
                    "common_job_for_all_pipelines is false"
                )
            else:
                # Collect all database names from configuration
                db_names = {db.get("name") for db in databases if db.get("name")}
                
                # Collect all database names covered by schedules
                scheduled_dbs = set()
                for i, sched in enumerate(per_db_schedules):
                    if not isinstance(sched, dict):
                        errors.append(f"job.per_database_schedules[{i}] must be an object")
                        continue
                    
                    if "name" not in sched:
                        errors.append(f"job.per_database_schedules[{i}].name is required")
                    
                    if "applies_to" not in sched:
                        errors.append(f"job.per_database_schedules[{i}].applies_to is required")
                    else:
                        applies_to = sched.get("applies_to", [])
                        if not isinstance(applies_to, list):
                            errors.append(
                                f"job.per_database_schedules[{i}].applies_to must be a list"
                            )
                        else:
                            scheduled_dbs.update(applies_to)
                            
                            # Check for databases that don't exist
                            invalid_dbs = set(applies_to) - db_names
                            if invalid_dbs:
                                errors.append(
                                    f"job.per_database_schedules[{i}].applies_to references "
                                    f"non-existent database(s): {', '.join(invalid_dbs)}"
                                )
                    
                    if "schedule" not in sched:
                        errors.append(f"job.per_database_schedules[{i}].schedule is required")
                    else:
                        sched_config = sched["schedule"]
                        if "quartz_cron_expression" not in sched_config:
                            errors.append(
                                f"job.per_database_schedules[{i}].schedule.quartz_cron_expression "
                                "is required"
                            )
                        if "timezone_id" not in sched_config:
                            errors.append(
                                f"job.per_database_schedules[{i}].schedule.timezone_id is required"
                            )
                
                # Check for databases not covered by any schedule
                unscheduled_dbs = db_names - scheduled_dbs
                if unscheduled_dbs:
                    errors.append(
                        f"The following database(s) are not covered by any schedule in "
                        f"job.per_database_schedules: {', '.join(sorted(unscheduled_dbs))}. "
                        f"Please add them to the 'applies_to' list of an appropriate schedule."
                    )
                
                # Check for duplicate database assignments
                db_to_schedules = {}
                for sched in per_db_schedules:
                    sched_name = sched.get("name", "unnamed")
                    for db in sched.get("applies_to", []):
                        if db in db_to_schedules:
                            errors.append(
                                f"Database '{db}' is assigned to multiple schedules: "
                                f"'{db_to_schedules[db]}' and '{sched_name}'"
                            )
                        else:
                            db_to_schedules[db] = sched_name

    # Validate Terraform variables
    terraform_vars = ["env", "app_name"]
    for var in terraform_vars:
        if var not in data:
            errors.append(f"Missing variable: {var}")
        elif not data[var] or not isinstance(data[var], str):
            errors.append(f"Variable {var} must be a non-empty string")

    if errors:
        print("Validation failed:\n - " + "\n - ".join(errors), file=sys.stderr)
        return 1

    print("YAML looks OK")
    return 0


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[1] / "config" / "lakeflow.yml"
    code = validate_yaml(path)
    sys.exit(code)


if __name__ == "__main__":
    main() 