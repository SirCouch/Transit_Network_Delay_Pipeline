output "project_id" {
  description = "GCP project ID."
  value       = var.project_id
}

output "region" {
  description = "Primary GCP region."
  value       = var.region
}

output "artifact_registry_repository" {
  description = "Docker Artifact Registry repository."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "raw_bucket_name" {
  description = "Raw GTFS feed bucket."
  value       = google_storage_bucket.raw_feeds.name
}

output "ingest_service_account" {
  description = "Cloud Run Job service account."
  value       = google_service_account.ingest_job.email
}

output "api_service_account" {
  description = "FastAPI service account."
  value       = google_service_account.api.email
}

output "dashboard_service_account" {
  description = "Streamlit dashboard service account."
  value       = google_service_account.dashboard.email
}

output "scheduler_service_account" {
  description = "Cloud Scheduler service account."
  value       = google_service_account.scheduler.email
}

output "serving_refresh_service_account" {
  description = "Serving refresh Cloud Run Job service account."
  value       = google_service_account.serving_refresh.email
}

output "retraining_service_account" {
  description = "Segment-risk retraining Cloud Run Job service account."
  value       = google_service_account.retraining.email
}

output "api_url" {
  description = "Public FastAPI Cloud Run URL."
  value       = google_cloud_run_v2_service.api.uri
}

output "dashboard_url" {
  description = "Public Streamlit Cloud Run URL."
  value       = google_cloud_run_v2_service.dashboard.uri
}

output "ingest_job_name" {
  description = "Cloud Run ingestion job name."
  value       = google_cloud_run_v2_job.ingest.name
}

output "serving_refresh_job_name" {
  description = "Cloud Run serving refresh job name."
  value       = google_cloud_run_v2_job.serving_refresh.name
}

output "retraining_job_name" {
  description = "Cloud Run segment-risk retraining job name."
  value       = google_cloud_run_v2_job.retraining.name
}

output "scheduler_job_name" {
  description = "Cloud Scheduler ingestion trigger."
  value       = google_cloud_scheduler_job.ingest.name
}

output "serving_refresh_scheduler_job_name" {
  description = "Cloud Scheduler serving refresh trigger."
  value       = google_cloud_scheduler_job.serving_refresh.name
}

output "retraining_scheduler_job_name" {
  description = "Cloud Scheduler segment-risk retraining trigger."
  value       = google_cloud_scheduler_job.retraining.name
}
