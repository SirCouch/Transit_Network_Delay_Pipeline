resource "google_service_account" "ingest_job" {
  project      = var.project_id
  account_id   = "transit-ingest-job-sa"
  display_name = "Transit ingestion Cloud Run Job"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "transit-api-sa"
  display_name = "Transit FastAPI Cloud Run service"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "dashboard" {
  project      = var.project_id
  account_id   = "transit-dashboard-sa"
  display_name = "Transit Streamlit Cloud Run service"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "serving_refresh" {
  project      = var.project_id
  account_id   = "transit-serving-refresh-sa"
  display_name = "Transit serving refresh Cloud Run Job"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "retraining" {
  project      = var.project_id
  account_id   = "transit-retraining-sa"
  display_name = "Transit segment risk retraining Cloud Run Job"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "transit-scheduler-sa"
  display_name = "Transit Cloud Scheduler invoker"

  depends_on = [google_project_service.required]
}
