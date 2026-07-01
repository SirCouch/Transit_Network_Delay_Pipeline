# Repository Guidelines

## Project Structure & Module Organization

This repo is the scaffold for a cloud-deployed MBTA transit delay pipeline. The planned production flow is `pipeline -> BigQuery -> api -> app`; `spark_jobs/` is reserved for a later PySpark proof-of-concept, not the deployed path.

Current key paths:
- `infra/terraform/`: GCP infrastructure as code for BigQuery, Cloud Run, Scheduler, IAM, Storage, and Artifact Registry.
- `docs/`: architecture and setup documentation. Local/private docs are ignored.
- `PLAN-1.md`: product and implementation plan; keep major scope decisions aligned with it.
- `workflow-orchestration.md`: local workflow expectations.
- `tests/fixtures/`: planned location for saved MBTA GTFS static and GTFS-RT snapshots.

## Build, Test, and Development Commands

Python project metadata lives in `pyproject.toml` and currently requires Python `>=3.11`.

Useful commands once tooling is installed:
- `python main.py`: run the current placeholder entrypoint.
- `terraform -chdir=infra/terraform fmt`: format Terraform.
- `terraform -chdir=infra/terraform init`: initialize providers/backend.
- `terraform -chdir=infra/terraform validate`: validate Terraform configuration.
- `terraform -chdir=infra/terraform plan`: preview GCP changes.

Do not run `terraform apply` until the dedicated GCP project, billing, quotas, and ignored `terraform.tfvars` are configured.

## Coding Style & Naming Conventions

Use Python 3.11+, 4-space indentation, type hints for public functions, and small modules grouped by responsibility. Use `snake_case` for Python files, functions, variables, and BigQuery fields.

Terraform resources should use descriptive names such as `google_cloud_run_v2_service.api` and variables should stay environment-neutral. Keep real values in ignored `.tfvars`, not committed files.

## Testing Guidelines

Use fixture-based tests with saved MBTA inputs under `tests/fixtures/`. Name tests `test_<behavior>.py` and prefer behavior-focused cases: GTFS parsing, edge-delay calculation, BigQuery write shapes, API degraded responses, and dashboard smoke checks.

Run the relevant test suite before marking work complete. Add tests when changing parsing, table schemas, API contracts, or cost-protection behavior.

## Commit & Pull Request Guidelines

No git history is present yet, so use clear conventional-style commits going forward, for example `feat: add ingestion job terraform` or `test: cover quota degraded response`.

PRs should include:
- Summary of behavior or infrastructure changed.
- Verification commands and results.
- Cost/security impact for GCP changes.
- Screenshots for dashboard UI changes.

## Security & Configuration Tips

Never commit `.tfvars`, Terraform state, service account keys, `.env` files, or private setup notes. The public API/dashboard are intentional, but Cloud Run max instances, BigQuery quotas, `maximum_bytes_billed`, and cached degraded responses are required cost controls.
