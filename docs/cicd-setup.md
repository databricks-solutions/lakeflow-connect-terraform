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

Two identities are used — one for state storage, one for Databricks deployment. No PAT tokens are used anywhere.

**TF State SPN** (Azure-only, for the `azurerm` Terraform backend):

| Secrets | Role |
|---------|------|
| `TF_STATE_ARM_CLIENT_ID`, `TF_STATE_ARM_CLIENT_SECRET`, `TF_STATE_ARM_SUBSCRIPTION_ID` | Storage Blob Data Contributor on the Azure Blob container holding Terraform state. Used only during `terraform init`. Never touches Databricks. |

`ARM_TENANT_ID` is the shared Azure AD tenant used by the TF State SPN.

**Deploy identity** (authenticates to the Databricks workspace):

The workflows support two auth options. The Databricks unified auth layer evaluates them in the order shown — set only the secrets for your target environment:

| Option | Secrets | Workspace support | Priority |
|--------|---------|-------------------|----------|
| **A — OAuth M2M** *(recommended)* | `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | Azure **and** AWS | Higher — evaluated first |
| **B — Azure SPN / Entra ID** | `DEPLOY_SPN_CLIENT_ID`, `DEPLOY_SPN_CLIENT_SECRET`, `ARM_TENANT_ID` | Azure only | Lower — used when Option A secrets are absent |

Both options coexist in the workflow `env:` blocks. If both sets of secrets are populated, OAuth M2M wins. If only the Azure SPN secrets are set, Entra ID auth is used. Set only what applies to your workspace.

See [Installation Guide — Step 4](installation.md#step-4-configure-terraform-backend) for a full explanation of the two-SPN model and backend setup.

## Required Repository Secrets

Configure these under **Settings → Secrets and variables → Actions → Secrets**:

**Always required:**

| Secret | Description | Used by |
|--------|-------------|---------|
| `DATABRICKS_HOST` | Databricks workspace URL (e.g. `https://adb-xxx.azuredatabricks.net` or `https://xxx.azuredatabricks.net`) | All workflows |
| `TF_STATE_ARM_CLIENT_ID` | Client ID of the **TF State SPN** — authenticates to Azure Blob backend | `terraform-deploy`, `terraform-release`, `terraform-output-pipeline-ids` |
| `TF_STATE_ARM_CLIENT_SECRET` | Client secret of the TF State SPN | same as above |
| `TF_STATE_ARM_SUBSCRIPTION_ID` | Azure subscription ID that contains the TF state storage account | same as above |
| `ARM_TENANT_ID` | Azure AD tenant ID — used by the TF State SPN and (if using Option B) the Deploy SPN | All workflows |

**Deploy identity — set Option A or Option B (not both required):**

| Secret | Option | Description | Used by |
|--------|--------|-------------|---------|
| `DATABRICKS_CLIENT_ID` | **A — OAuth M2M** | OAuth client ID of the Databricks service principal | All workflows |
| `DATABRICKS_CLIENT_SECRET` | **A — OAuth M2M** | OAuth client secret of the Databricks service principal | All workflows |
| `DEPLOY_SPN_CLIENT_ID` | **B — Azure SPN** | Entra ID application (client) ID of the Deploy SPN | All workflows |
| `DEPLOY_SPN_CLIENT_SECRET` | **B — Azure SPN** | Entra ID client secret of the Deploy SPN | All workflows |

> If both Option A and Option B secrets are configured, the Databricks Terraform provider will error with "more than one authorization method configured". Set `DATABRICKS_AUTH_TYPE` (see Required Repository Variables below) to resolve the conflict explicitly.

## Required Repository Variables

Configure these under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Description | Used by |
|----------|-------------|---------|
| `TF_STATE_RESOURCE_GROUP` | Azure Resource Group containing the TF state storage account | `terraform-deploy`, `terraform-release`, `terraform-output-pipeline-ids` |
| `TF_STATE_STORAGE_ACCOUNT` | Azure Storage Account name | same as above |
| `TF_STATE_CONTAINER` | Blob container name within the storage account | same as above |
| `TF_STATE_KEY` | Blob path/filename for the `.tfstate` file (e.g. `lakeflow-connect/terraform.tfstate`) | same as above |
| `DATABRICKS_AUTH_TYPE` | Databricks authentication method. Set to `oauth-m2m` (AWS or Azure OAuth M2M) or `azure-client-secret` (Azure SPN). **Required when both Option A and Option B secrets are configured** to prevent a Terraform provider conflict; leave unset if only one credential set is present. | All workflows |

## Required Databricks Permissions for the Deploy Identity

The service principal used for Terraform plan/apply (Option A OAuth M2M or Option B Azure SPN) must have the following permissions granted in the Databricks workspace **before** running any workflow:

| Permission | Scope | Why |
|------------|-------|-----|
| `USE CONNECTION` | Unity Catalog connection to the source database | Required to attach the connection to the gateway pipeline |
| `USE CATALOG` | Every catalog referenced in the YAML config (`global_uc_catalog`, `staging_uc_catalog`) | Required for Terraform to manage resources within those catalogs |
| `USE SCHEMA` + `CREATE TABLE` | Every ingestion pipeline target schema | Required to create and manage ingestion pipeline tables |
| `USE SCHEMA` + `CREATE TABLE` + `CREATE VOLUME` | Staging schema | Required for event log tables and staging volumes |
| **`CAN USE`** | **Cluster policy named in `gateway_pipeline_cluster_policy_name`** | **Required for the gateway pipeline to spin up compute using that policy. Without this, the gateway pipeline creation fails even if the policy name is correct.** |

### Granting CAN USE on a Cluster Policy

The `gateway_pipeline_cluster_policy_name` field in your YAML config references a cluster policy by name. The deploy service principal must be explicitly granted `CAN USE` on that policy:

1. In the Databricks workspace, go to **Compute → Policies**
2. Find the policy referenced in your YAML config
3. Click **Permissions** on the policy
4. Add the deploy service principal with **Can Use** permission

This applies to both OAuth M2M service principals (Option A) and Azure Entra ID service principals (Option B).

## Required Branch Protection

By default, the `main` branch has no protection rules. Hence, without setting them up, the CI checks are optional and a PR can be merged even if they fail. To make the plan check a required gate before merging, use either approach below.

### Option A — Rulesets (recommended)

Rulesets are GitHub's modern branch protection mechanism. They support dry-run (Evaluation) mode before enforcing, and can be reused across repos at the org level.

1. Go to **Settings → Rules → Rulesets → New ruleset → New branch ruleset**
2. Set **Ruleset name** to e.g. `Protect main`
3. Set **Enforcement status** to `Active`
4. Under **Target branches**, add `main` (or use `Default branch`)
5. Enable **Require a pull request before merging**
6. Enable **Require status checks to pass**, then add the following required checks:
   - `Validate`
   - `Plan`
7. Optionally enable **Require branches to be up to date before merging**
8. Save the ruleset

### Option B — Classic branch protection rules

1. Go to **Settings → Branches → Add branch protection rule**
2. Set **Branch name pattern** to `main`
3. Enable **Require status checks to pass before merging**
4. Search for and add the following required checks:
   - `Validate`
   - `Plan`
5. Optionally enable **Require branches to be up to date before merging**
6. Save the rule

> **Note:** Status checks only appear in the search list after they have run at least once on a PR. Trigger a test PR first, then come back to add them as required checks.

## Optional: GitHub Environments for Approval Gates

The deploy and refresh workflows support human approval gates via [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment). To enable them:

1. Create an environment named **`production-deploy`** (for Terraform apply) and/or **`production-refresh`** (for pipeline refresh jobs) under **Settings → Environments**.
2. Add required reviewers to each environment.
3. Uncomment the `environment:` block in the relevant workflow job (search for `# environment:` in the workflow files).

> Approval gates require **GitHub Pro, Team, or Enterprise** for private repositories.

## Rollback

See the header comments in `.github/workflows/terraform-release.yml` for the two recommended rollback strategies (git revert on `main`, or manual `workflow_dispatch` from an older branch).
