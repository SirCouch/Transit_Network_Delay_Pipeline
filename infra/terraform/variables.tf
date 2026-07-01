variable "project_id" {
  description = "Dedicated GCP project ID for the transit delay pipeline."
  type        = string
}

variable "region" {
  description = "Primary region for Cloud Run, Cloud Scheduler, Artifact Registry, and regional buckets."
  type        = string
  default     = "us-central1"
}

variable "storage_location" {
  description = "Cloud Storage bucket location. Use a free-tier eligible US region for this portfolio project."
  type        = string
  default     = "US-CENTRAL1"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"
}

variable "labels" {
  description = "Additional labels applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "raw_bucket_name" {
  description = "Optional globally unique raw feed bucket name. Defaults to PROJECT_ID-gtfs-raw."
  type        = string
  default     = null
}

variable "artifact_registry_repo_id" {
  description = "Artifact Registry Docker repository ID."
  type        = string
  default     = "transit-delay-images"
}

variable "ingest_image" {
  description = "Container image for the Cloud Run ingestion job. Replace the placeholder after building the job image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "api_image" {
  description = "Container image for the FastAPI Cloud Run service. Replace the placeholder after building the API image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "dashboard_image" {
  description = "Container image for the Streamlit Cloud Run service. Replace the placeholder after building the dashboard image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "mbta_static_url" {
  description = "MBTA GTFS Static zip URL. Kept configurable so feed URLs can be updated without code changes."
  type        = string
  default     = ""
}

variable "mbta_trip_updates_url" {
  description = "MBTA GTFS-RT TripUpdates protobuf URL. Kept configurable so feed URLs can be updated without code changes."
  type        = string
  default     = ""
}

variable "refresh_mode" {
  description = "Pipeline refresh mode. Use cost_safe for production and demo only during active recordings."
  type        = string
  default     = "cost_safe"

  validation {
    condition     = contains(["cost_safe", "demo"], var.refresh_mode)
    error_message = "refresh_mode must be either cost_safe or demo."
  }
}

variable "scheduler_cron" {
  description = "Cloud Scheduler cron expression for the ingestion job."
  type        = string
  default     = "*/30 * * * *"
}

variable "serving_scheduler_cron" {
  description = "Cloud Scheduler cron expression for the serving-table refresh job."
  type        = string
  default     = "0 * * * *"
}

variable "retraining_scheduler_cron" {
  description = "Cloud Scheduler cron expression for the model retraining job."
  type        = string
  default     = "0 3 * * 0"
}

variable "retraining_scheduler_paused" {
  description = "Whether the model retraining scheduler should be paused."
  type        = bool
  default     = true
}

variable "scheduler_time_zone" {
  description = "Time zone for Cloud Scheduler."
  type        = string
  default     = "America/New_York"
}

variable "api_max_bytes_billed" {
  description = "Maximum BigQuery bytes billed per API query."
  type        = number
  default     = 26214400
}

variable "api_rate_limit_enabled" {
  description = "Whether the public API should enforce in-process rate limiting."
  type        = bool
  default     = true
}

variable "api_rate_limit_requests" {
  description = "Maximum API requests per client within the rate-limit window."
  type        = number
  default     = 120
}

variable "api_rate_limit_window_seconds" {
  description = "API rate-limit window in seconds."
  type        = number
  default     = 60
}

variable "api_response_cache_ttl_seconds" {
  description = "Seconds to cache BigQuery serving query results inside the API instance."
  type        = number
  default     = 300
}

variable "ingest_job_timeout" {
  description = "Cloud Run Job task timeout."
  type        = string
  default     = "900s"
}

variable "serving_refresh_job_timeout" {
  description = "Cloud Run serving refresh Job task timeout."
  type        = string
  default     = "1200s"
}

variable "retraining_job_timeout" {
  description = "Cloud Run retraining Job task timeout."
  type        = string
  default     = "3600s"
}

variable "retraining_cpu" {
  description = "CPU limit for the Cloud Run retraining Job. Higher than serving because training materializes recent snapshots in memory."
  type        = string
  default     = "4"
}

variable "retraining_memory" {
  description = "Memory limit for the Cloud Run retraining Job."
  type        = string
  default     = "16Gi"
}

variable "serving_recent_snapshot_count" {
  description = "Number of recent raw TripUpdates snapshots used to refresh serving tables."
  type        = number
  default     = 4
}

variable "retraining_recent_snapshot_count" {
  description = "Number of recent raw TripUpdates snapshots used by the retraining job."
  type        = number
  default     = 168
}

variable "retraining_horizon_minutes" {
  description = "Future-label horizon for the segment-risk retraining job. Keep this at or above the ingestion cadence."
  type        = number
  default     = 35
}

variable "retraining_promote_model" {
  description = "Whether retraining should overwrite the active model artifact used by serving refresh."
  type        = bool
  default     = false
}

variable "serving_max_network_rows" {
  description = "Maximum current-network rows written to serving tables."
  type        = number
  default     = 10000
}

variable "service_timeout" {
  description = "Cloud Run service request timeout."
  type        = string
  default     = "300s"
}

variable "bigquery_deletion_protection" {
  description = "Whether BigQuery tables should have deletion protection enabled."
  type        = bool
  default     = false
}

variable "billing_account_id" {
  description = "Optional billing account ID for Terraform-managed budget alerts. Leave null to manage budgets manually."
  type        = string
  default     = null
}

variable "budget_alert_emails" {
  description = "Email addresses to notify for Terraform-managed budget alerts."
  type        = list(string)
  default     = []
}

variable "monthly_budget_amount" {
  description = "Monthly budget amount in USD when billing_account_id and budget_alert_emails are set."
  type        = number
  default     = 5
}
