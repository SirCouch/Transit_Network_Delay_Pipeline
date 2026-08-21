resource "google_cloud_scheduler_job" "ingest" {
  project     = var.project_id
  region      = var.region
  name        = "transit-ingest-schedule"
  description = "Runs the MBTA ingestion Cloud Run Job on the cost-safe cadence"
  schedule    = var.scheduler_cron
  time_zone   = var.scheduler_time_zone
  paused      = var.ingest_scheduler_paused

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.ingest.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_job_iam_member.scheduler_can_run_ingest,
  ]
}

resource "google_cloud_scheduler_job" "serving_refresh" {
  project     = var.project_id
  region      = var.region
  name        = "transit-serving-refresh-schedule"
  description = "Refreshes BigQuery serving tables from recent raw MBTA snapshots"
  schedule    = var.serving_scheduler_cron
  time_zone   = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.serving_refresh.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_job_iam_member.scheduler_can_run_serving_refresh,
  ]
}

resource "google_cloud_scheduler_job" "retraining" {
  project     = var.project_id
  region      = var.region
  name        = "transit-segment-risk-retraining-schedule"
  description = "Runs the segment-risk model retraining Cloud Run Job"
  schedule    = var.retraining_scheduler_cron
  time_zone   = var.scheduler_time_zone
  paused      = var.retraining_scheduler_paused

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.retraining.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_job_iam_member.scheduler_can_run_retraining,
  ]
}
