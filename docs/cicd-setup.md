# GitHub Actions CI/CD Setup

This repository ships with five GitHub Actions workflows that run on a **self-hosted runner** and automate the full deployment and refresh lifecycle.

## Workflows Overview

| Workflow file | Trigger | Purpose |
|---------------|---------|---------|
| `terraform-deploy.yml` | PR targeting `main` (validate + plan) or `workflow_dispatch` | Validate → Plan on PRs; Plan → Apply or Destroy on manual dispatch |
| `terraform-release.yml` | Semver tag push (e.g. `v1.0.0`) | Tag-gated Validate → Plan → Apply; tag must be tip of `main` |
| `terraform-output-pipeline-ids.yml` | `workflow_dispatch` | Read-only: list all pipeline IDs from Terraform state |
| `full-refresh-pipeline.yml` | `workflow_dispatch` | Trigger a full refresh of an entire ingestion pipeline |
| `full-refresh-tables.yml` | `workflow_dispatch` | Trigger a full refresh of specific tables within a pipeline |

### Deployment workflow details

**`terraform-deploy.yml`** is the day-to-day IaC workflow:
- **On PR**: runs Validate + Plan automatically (path-filtered: `infra/**`, `config/**`, `tools/**`). No apply is triggered — the plan output appears in the PR checks for reviewers to inspect before merging.
- **On `workflow_dispatch`**: supports `plan-only`, `plan-and-apply`, and `destroy` actions with a configurable config file path.

**`terraform-release.yml`** is for production releases:
- Triggered by a semver tag (e.g. `v1.0.0`) pushed to the tip of `main`. A guard job aborts if the tag does not point at the current `HEAD` of `main`.
- Runs the full Validate → Plan → Apply cycle. Apply runs plan-to-file then applies exactly that plan within the same job.

## Self-Hosted Runner Prerequisites

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

## Authentication Model

Two separate Azure service principals (SPNs) are used — one for state storage, one for Databricks deployment. No PAT tokens are used anywhere.

| SPN | Secrets | Role |
|-----|---------|------|
| **TF State SPN** | `TF_STATE_ARM_CLIENT_ID`, `TF_STATE_ARM_CLIENT_SECRET`, `TF_STATE_ARM_SUBSCRIPTION_ID` | Storage Blob Data Contributor on the Azure Blob container holding Terraform state. Used only during `terraform init`. Never touches Databricks. |
| **Deploy SPN** | `DEPLOY_SPN_CLIENT_ID`, `DEPLOY_SPN_CLIENT_SECRET` | Service principal registered in Databricks workspace. Used by the Databricks Terraform provider (`ARM_*` env vars) and Databricks SDK during `terraform plan/apply` and refresh workflows. |

`ARM_TENANT_ID` is the shared Azure AD tenant — used by both SPNs.

See [Installation Guide — Step 4](installation.md#step-4-configure-terraform-backend) for a full explanation of the two-SPN model and backend setup.

## Required Repository Secrets

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

## Required Repository Variables

Configure these under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Description | Used by |
|----------|-------------|---------|
| `TF_STATE_RESOURCE_GROUP` | Azure Resource Group containing the TF state storage account | `terraform-deploy`, `terraform-release`, `terraform-output-pipeline-ids` |
| `TF_STATE_STORAGE_ACCOUNT` | Azure Storage Account name | same as above |
| `TF_STATE_CONTAINER` | Blob container name within the storage account | same as above |
| `TF_STATE_KEY` | Blob path/filename for the `.tfstate` file (e.g. `lakeflow-connect/terraform.tfstate`) | same as above |

## Optional: GitHub Environments for Approval Gates

The deploy and refresh workflows support human approval gates via [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment). To enable them:

1. Create an environment named **`production-deploy`** (for Terraform apply) and/or **`production-refresh`** (for pipeline refresh jobs) under **Settings → Environments**.
2. Add required reviewers to each environment.
3. Uncomment the `environment:` block in the relevant workflow job (search for `# environment:` in the workflow files).

> Approval gates require **GitHub Pro, Team, or Enterprise** for private repositories.

## Rollback

See the header comments in `.github/workflows/terraform-release.yml` for the two recommended rollback strategies (git revert on `main`, or manual `workflow_dispatch` from an older branch).
