# GCP Project Shape

This example shows the rough Terraform shape of the MBTA delay pipeline on Google Cloud.

It is intentionally smaller than `infra/terraform/`. Use it to learn how resources relate to each other:

- `google_storage_bucket.raw_feeds` stores raw GTFS and GTFS-RT snapshots.
- `google_bigquery_dataset.transit` holds analytical tables.
- `google_service_account.pipeline` is the runtime identity.
- `google_cloud_run_v2_job.ingest` represents the scheduled ingestion job.
- Outputs expose names that are useful after deployment.

Do not apply this directory against a real project unless you intentionally want to create these sample resources. For real deployment work, use `infra/terraform/`.

Good comparison files:

- `infra/terraform/bigquery.tf`
- `infra/terraform/storage.tf`
- `infra/terraform/cloud_run.tf`
- `infra/terraform/scheduler.tf`
- `infra/terraform/service_accounts.tf`
- `infra/terraform/iam.tf`
