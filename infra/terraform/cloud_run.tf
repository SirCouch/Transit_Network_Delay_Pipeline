resource "google_cloud_run_v2_job" "ingest" {
  project  = var.project_id
  name     = local.services.ingest
  location = var.region
  labels   = local.common_labels

  template {
    template {
      service_account = google_service_account.ingest_job.email
      timeout         = var.ingest_job_timeout

      containers {
        image = var.ingest_image

        env {
          name  = "REFRESH_MODE"
          value = var.refresh_mode
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "RAW_BUCKET_NAME"
          value = google_storage_bucket.raw_feeds.name
        }

        env {
          name  = "MBTA_STATIC_URL"
          value = var.mbta_static_url
        }

        env {
          name  = "MBTA_TRIP_UPDATES_URL"
          value = var.mbta_trip_updates_url
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.ingest_raw_bucket_writer,
  ]
}

resource "google_cloud_run_v2_job" "serving_refresh" {
  project  = var.project_id
  name     = local.services.serving_refresh
  location = var.region
  labels   = local.common_labels

  template {
    template {
      service_account = google_service_account.serving_refresh.email
      timeout         = var.serving_refresh_job_timeout

      containers {
        image   = var.ingest_image
        command = ["python"]
        args = [
          "-m",
          "pipeline.cloud_serving",
          "--bucket",
          google_storage_bucket.raw_feeds.name,
          "--static-zip",
          "gs://${google_storage_bucket.raw_feeds.name}/artifacts/MBTA_GTFS.zip",
          "--model",
          "gs://${google_storage_bucket.raw_feeds.name}/artifacts/segment_risk_model.joblib",
          "--output-dir",
          "/tmp/local_serving",
          "--project-id",
          var.project_id,
          "--serving-dataset",
          google_bigquery_dataset.serving.dataset_id,
          "--monitoring-dataset",
          google_bigquery_dataset.monitoring.dataset_id,
          "--recent-snapshot-count",
          tostring(var.serving_recent_snapshot_count),
          "--max-network-rows",
          tostring(var.serving_max_network_rows),
          "--write-bigquery",
          "--write-monitoring",
        ]

        resources {
          limits = {
            cpu    = "1"
            memory = "4Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.serving_refresh_raw_bucket_viewer,
    google_project_iam_member.serving_refresh_bigquery_job_user,
    google_bigquery_dataset_iam_member.serving_refresh_serving_editor,
    google_bigquery_dataset_iam_member.serving_refresh_monitoring_editor,
  ]
}

resource "google_cloud_run_v2_job" "retraining" {
  project  = var.project_id
  name     = local.services.retraining
  location = var.region
  labels   = local.common_labels

  template {
    template {
      service_account = google_service_account.retraining.email
      timeout         = var.retraining_job_timeout

      containers {
        image   = var.ingest_image
        command = ["python"]
        args = concat(
          [
            "-m",
            "pipeline.retrain_segment_risk",
            "--bucket",
            google_storage_bucket.raw_feeds.name,
            "--static-zip",
            "gs://${google_storage_bucket.raw_feeds.name}/artifacts/MBTA_GTFS.zip",
            "--project-id",
            var.project_id,
            "--monitoring-dataset",
            google_bigquery_dataset.monitoring.dataset_id,
            "--recent-snapshot-count",
            tostring(var.retraining_recent_snapshot_count),
            "--horizon-minutes",
            tostring(var.retraining_horizon_minutes),
            "--output-prefix",
            "artifacts/models/segment-risk",
          ],
          var.retraining_promote_model ? ["--promote"] : [],
        )

        resources {
          limits = {
            cpu    = var.retraining_cpu
            memory = var.retraining_memory
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_storage_bucket_iam_member.retraining_raw_bucket_admin,
    google_project_iam_member.retraining_bigquery_job_user,
    google_bigquery_dataset_iam_member.retraining_monitoring_editor,
  ]
}

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = local.services.api
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.common_labels

  template {
    service_account                  = google_service_account.api.email
    timeout                          = var.service_timeout
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "GTFS_SERVING_DATASET"
        value = google_bigquery_dataset.serving.dataset_id
      }

      env {
        name  = "BIGQUERY_MAX_BYTES_BILLED"
        value = tostring(var.api_max_bytes_billed)
      }

      env {
        name  = "API_RATE_LIMIT_ENABLED"
        value = tostring(var.api_rate_limit_enabled)
      }

      env {
        name  = "API_RATE_LIMIT_REQUESTS"
        value = tostring(var.api_rate_limit_requests)
      }

      env {
        name  = "API_RATE_LIMIT_WINDOW_SECONDS"
        value = tostring(var.api_rate_limit_window_seconds)
      }

      env {
        name  = "API_RESPONSE_CACHE_TTL_SECONDS"
        value = tostring(var.api_response_cache_ttl_seconds)
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.api_bigquery_job_user,
    google_bigquery_dataset_iam_member.api_serving_viewer,
  ]
}

resource "google_cloud_run_v2_service" "dashboard" {
  project  = var.project_id
  name     = local.services.dashboard
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.common_labels

  template {
    service_account                  = google_service_account.dashboard.email
    timeout                          = var.service_timeout
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.dashboard_image

      ports {
        container_port = 8080
      }

      env {
        name  = "API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.dashboard.location
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run_ingest" {
  project  = var.project_id
  location = google_cloud_run_v2_job.ingest.location
  name     = google_cloud_run_v2_job.ingest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run_serving_refresh" {
  project  = var.project_id
  location = google_cloud_run_v2_job.serving_refresh.location
  name     = google_cloud_run_v2_job.serving_refresh.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run_retraining" {
  project  = var.project_id
  location = google_cloud_run_v2_job.retraining.location
  name     = google_cloud_run_v2_job.retraining.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}
