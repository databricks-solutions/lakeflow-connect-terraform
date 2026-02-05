#!/usr/bin/env python3
"""
Script to validate that the gateway pipeline is running successfully.
This script can be executed as arbitrary code from Terraform after the gateway_pipeline module. 
It will wait for the gateway to be in RUNNING state before the job resource is created/updated, unless a timeout is encountered based on configuration defined.
"""

import sys
import time
import yaml
import argparse
from pathlib import Path
from datetime import datetime, timezone
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.pipelines import UpdateInfoState
from typing import Union, Optional


def format_timestamp(timestamp_ms: Union[int, str]) -> str:
    """Convert timestamp in milliseconds to YYYY-MM-DD HH:mm:ss UTC format."""
    try:
        if isinstance(timestamp_ms, str):
            timestamp_ms = int(timestamp_ms)
        timestamp_s = timestamp_ms / 1000
        dt = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return str(timestamp_ms) # Fallback to original format if conversion fails

def get_latest_pipeline_update(workspace_client: WorkspaceClient, 
                              pipeline_id: str, 
                              max_results: int = 10,
                              next_token: Union[str, None] = None) :
    """Get the latest update for a pipeline."""

    consolidated_list_of_updates = list()

    while True:
        try:
            response = workspace_client.pipelines.list_updates(
                pipeline_id=pipeline_id, 
                max_results=max_results,
                page_token=next_token
            )
            consolidated_list_of_updates.extend(response.updates)
        except Exception as e:
            raise Exception(f"Failed to get pipeline updates: {e}")

        if response.next_page_token:
            next_token = response.next_page_token
        else:
            break

    if len(consolidated_list_of_updates) == 0:
        raise Exception("No pipeline updates were retrieved for this valid pipeline ID")

    # In-place sort in descending order of creation_time of the pipeline update and return the latest update
    consolidated_list_of_updates.sort(key = lambda item : item.creation_time, reverse=True)
    return consolidated_list_of_updates[0]



def validate_ingestion_pipelines(workspace_client: WorkspaceClient, 
                                ingestion_pipeline_ids: list[str],
                                start_time: float,
                                timeout_seconds: int,
                                check_interval_seconds: int) -> bool:
    """
    Trigger validate-only runs for ingestion pipelines.
    
    Args:
        workspace_client: Databricks workspace client
        ingestion_pipeline_ids: List of ingestion pipeline IDs to validate
        start_time: Start time of the gateway pipeline validation
        timeout_seconds: Timeout in seconds for the ingestion pipeline validation
        check_interval_seconds: Interval between checks
    Returns:
        bool: True if all validation runs were triggered successfully
    """
    print(f"Starting validate-only runs for {len(ingestion_pipeline_ids)} ingestion pipelines...", flush=True)
    
    try:
        for pipeline_id in ingestion_pipeline_ids:
            print(f"Triggering validate-only run for ingestion pipeline: {pipeline_id}", flush=True)
            workspace_client.pipelines.start_update(pipeline_id=pipeline_id, validate_only=True)
            print(f"Validate-only run triggered successfully for pipeline: {pipeline_id}", flush=True)

        # Wait for all ingestion pipelines to reach COMPLETED state within timeout_seconds
        if ingestion_pipeline_ids:
            print(f"Waiting for {len(ingestion_pipeline_ids)} ingestion pipelines to reach COMPLETED state...", flush=True)
            completed_pipelines = set()
            while True:
                for pipeline_id in ingestion_pipeline_ids:
                    if pipeline_id in completed_pipelines:
                        continue
                    try:
                        latest_update = get_latest_pipeline_update(workspace_client, pipeline_id)
                        state = latest_update.state
                        print(f"Ingestion pipeline {pipeline_id} state: {state}", flush=True)
                        if state == UpdateInfoState.COMPLETED:
                            print(f"Ingestion pipeline {pipeline_id} has reached COMPLETED state.", flush=True)
                            completed_pipelines.add(pipeline_id)
                        elif state in [UpdateInfoState.WAITING_FOR_RESOURCES, UpdateInfoState.QUEUED, UpdateInfoState.INITIALIZING
                                    , UpdateInfoState.SETTING_UP_TABLES, UpdateInfoState.RESETTING]:
                            print(f"Ingestion pipeline {pipeline_id} is in {state} state. Still waiting for resources. Next update in {check_interval_seconds} seconds...", flush=True)
                        elif state in [UpdateInfoState.FAILED, UpdateInfoState.CANCELED]:
                            raise Exception(f"Ingestion pipeline {pipeline_id} failed or was canceled (state: {state})")
                    except Exception as e:
                        print(f"Error checking state for ingestion pipeline {pipeline_id}: {e}", flush=True)
                        raise Exception(f"Failed to check ingestion pipeline {pipeline_id}: {e}")
                if len(completed_pipelines) == len(ingestion_pipeline_ids):
                    print("All ingestion pipelines have reached COMPLETED state.", flush=True)
                    break
                if (time.time() - start_time) > timeout_seconds:
                    raise Exception("Timeout reached while waiting for ingestion pipelines to complete.")
                time.sleep(check_interval_seconds)
        print("All ingestion pipeline validate-only runs triggered successfully!", flush=True)
        return True
        
    except Exception as e:
        print(f"Error triggering ingestion pipeline validation: {e}", flush=True)
        raise Exception(f"Failed to trigger ingestion pipeline validation: {e}")


def validate_gateway_pipeline(pipeline_id: str, 
                             timeout_minutes: int, 
                             check_interval_seconds: int,
                             ingestion_pipeline_ids: list[str] = None) -> bool:
    """
    Validate that the gateway pipeline is in RUNNING state.
    
    Args:
        pipeline_id: The ID of the pipeline to validate
        timeout_minutes: Maximum time to wait for pipeline to start running
        check_interval_seconds: Interval between checks
        ingestion_pipeline_ids: Optional list of ingestion pipeline IDs to validate after gateway is running
    
    Returns:
        bool: True if pipeline is running, False otherwise
    
    Raises:
        Exception: If validation fails or timeout is reached
    """
    
    # Initialize workspace client
    try:
        w = WorkspaceClient()
    except Exception as e:
        raise Exception(f"Failed to initialize Databricks workspace client: {e}")
    
    print(f"Starting gateway pipeline validation for pipeline ID: {pipeline_id}", flush=True)
    print(f"Timeout: {timeout_minutes} minutes, Check interval: {check_interval_seconds} seconds", flush=True)
    
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    
    while True:
        try:
            latest_update = get_latest_pipeline_update(w, pipeline_id)
            
            if not latest_update:
                print("No pipeline updates found. Pipeline may not exist yet.", flush=True)
            else:
                state = latest_update.state
                creation_time = latest_update.creation_time
                
                formatted_time = format_timestamp(creation_time)
                print(f"Pipeline state: {state} (Last update: {formatted_time})", flush=True)
                
                if state == UpdateInfoState.RUNNING:
                    print("Gateway pipeline is now RUNNING successfully!", flush=True)
                    
                    # If ingestion pipeline IDs are provided, trigger their validation
                    if ingestion_pipeline_ids:
                        print("Gateway pipeline is running. Now triggering ingestion pipeline validation...", flush=True)
                        validate_ingestion_pipelines(w, ingestion_pipeline_ids,start_time=start_time,timeout_seconds=timeout_seconds,check_interval_seconds=check_interval_seconds)
                        print("Ingestion pipeline validation completed successfully!", flush=True)
                    
                    return True
                    
                elif state in [UpdateInfoState.FAILED, UpdateInfoState.CANCELED]:
                    print(f"Gateway pipeline reached end state: {state}", flush=True)
                    raise Exception(f"Gateway pipeline failed with state: {state}")
                    
                elif state == UpdateInfoState.COMPLETED:
                    print("Gateway pipeline completed. This is not expected for a continuous running gateway pipeline.", flush=True)
                    return True
                    
                elif state in [UpdateInfoState.WAITING_FOR_RESOURCES, UpdateInfoState.QUEUED, UpdateInfoState.INITIALIZING
                               , UpdateInfoState.SETTING_UP_TABLES, UpdateInfoState.RESETTING]:
                    print(f"Pipeline is {state}. Still waiting for resources. Next update in {check_interval_seconds} seconds...", flush=True)
            
        except Exception as e:
            raise Exception(f"Error checking pipeline status: {e}")
        
        # Check if timeout reached
        elapsed_time = time.time() - start_time
        if elapsed_time >= timeout_seconds:
            raise Exception(f"Timeout reached after {timeout_minutes} minutes. Gateway pipeline did not start running. Pipeline is in state at time of timeout: {state}")
        
        # Wait before next check
        remaining_time = timeout_seconds - elapsed_time
        print(f"Waiting {check_interval_seconds} seconds before next check... (Remaining: {remaining_time/60:.1f} minutes)", flush=True)
        time.sleep(check_interval_seconds)


def main():
    """Main function to run the gateway validation."""
    parser = argparse.ArgumentParser(description="Validate gateway pipeline is running")
    parser.add_argument("--pipeline-id", required=True, help="Pipeline ID to validate")
    parser.add_argument("--timeout", type=int, help="Timeout in minutes")
    parser.add_argument("--check-interval", type=int, help="Check interval in seconds")
    parser.add_argument("--ingestion-pipeline-ids", nargs="*", help="List of ingestion pipeline IDs to validate after gateway is running")
    
    args = parser.parse_args()
    
    try:
        timeout_minutes = args.timeout
        check_interval_seconds = args.check_interval
        
        # Validate gateway pipeline
        success = validate_gateway_pipeline(
            pipeline_id=args.pipeline_id,
            timeout_minutes=timeout_minutes,
            check_interval_seconds=check_interval_seconds,
            ingestion_pipeline_ids=args.ingestion_pipeline_ids
        )
        
        if success:
            print("Gateway pipeline validation completed successfully!", flush=True)
            sys.exit(0)
        else:
            print("Gateway pipeline validation failed!", flush=True)
            sys.exit(1)
            
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()