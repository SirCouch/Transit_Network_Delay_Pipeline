resource "google_project_iam_member" "ingest_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_project_iam_member" "api_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "serving_refresh_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.serving_refresh.email}"
}

resource "google_project_iam_member" "retraining_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.retraining.email}"
}

resource "google_storage_bucket_iam_member" "ingest_raw_bucket_writer" {
  bucket = google_storage_bucket.raw_feeds.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_storage_bucket_iam_member" "serving_refresh_raw_bucket_viewer" {
  bucket = google_storage_bucket.raw_feeds.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.serving_refresh.email}"
}

resource "google_storage_bucket_iam_member" "retraining_raw_bucket_admin" {
  bucket = google_storage_bucket.raw_feeds.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.retraining.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_static_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.static.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_graph_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.graph.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_rt_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.rt.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_analytics_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_serving_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.serving.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_job.email}"
}

resource "google_bigquery_dataset_iam_member" "api_serving_viewer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.serving.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.api.email}"
}

resource "google_bigquery_dataset_iam_member" "serving_refresh_serving_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.serving.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.serving_refresh.email}"
}

resource "google_bigquery_dataset_iam_member" "serving_refresh_monitoring_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.monitoring.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.serving_refresh.email}"
}

resource "google_bigquery_dataset_iam_member" "retraining_monitoring_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.monitoring.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.retraining.email}"
}
