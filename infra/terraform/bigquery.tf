resource "google_bigquery_dataset" "static" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.static
  location                   = "US"
  description                = "Parsed MBTA GTFS Static tables"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "graph" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.graph
  location                   = "US"
  description                = "Static transit graph tables"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "rt" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.rt
  location                   = "US"
  description                = "Realtime MBTA GTFS-RT state and snapshots"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "analytics" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.analytics
  location                   = "US"
  description                = "Delay exposure and bottleneck analytics"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "serving" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.serving
  location                   = "US"
  description                = "Small current-state tables for public API and dashboard reads"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "monitoring" {
  project                    = var.project_id
  dataset_id                 = local.dataset_ids.monitoring
  location                   = "US"
  description                = "Production model monitoring and retraining audit logs"
  delete_contents_on_destroy = false
  labels                     = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "stops" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.static.dataset_id
  table_id            = "stops"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "stop_id", type = "STRING", mode = "REQUIRED" },
    { name = "stop_name", type = "STRING", mode = "NULLABLE" },
    { name = "stop_lat", type = "FLOAT", mode = "NULLABLE" },
    { name = "stop_lon", type = "FLOAT", mode = "NULLABLE" },
    { name = "geom", type = "GEOGRAPHY", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "routes" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.static.dataset_id
  table_id            = "routes"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "route_id", type = "STRING", mode = "REQUIRED" },
    { name = "route_short_name", type = "STRING", mode = "NULLABLE" },
    { name = "route_long_name", type = "STRING", mode = "NULLABLE" },
    { name = "route_type", type = "INTEGER", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "trips" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.static.dataset_id
  table_id            = "trips"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "trip_id", type = "STRING", mode = "REQUIRED" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "service_id", type = "STRING", mode = "NULLABLE" },
    { name = "direction_id", type = "INTEGER", mode = "NULLABLE" },
    { name = "shape_id", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "stop_times" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.static.dataset_id
  table_id            = "stop_times"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels
  clustering          = ["trip_id", "stop_id"]

  schema = jsonencode([
    { name = "trip_id", type = "STRING", mode = "REQUIRED" },
    { name = "stop_id", type = "STRING", mode = "REQUIRED" },
    { name = "stop_sequence", type = "INTEGER", mode = "REQUIRED" },
    { name = "arrival_time", type = "STRING", mode = "NULLABLE" },
    { name = "departure_time", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "static_edges" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.graph.dataset_id
  table_id            = "static_edges"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels
  clustering          = ["route_id", "trip_id", "src_stop_id", "dst_stop_id"]

  schema = jsonencode([
    { name = "edge_id", type = "STRING", mode = "REQUIRED" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "direction_id", type = "INTEGER", mode = "NULLABLE" },
    { name = "trip_id", type = "STRING", mode = "NULLABLE" },
    { name = "pattern_id", type = "STRING", mode = "NULLABLE" },
    { name = "src_stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "dst_stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "src_stop_sequence", type = "INTEGER", mode = "NULLABLE" },
    { name = "dst_stop_sequence", type = "INTEGER", mode = "NULLABLE" },
    { name = "scheduled_departure_time", type = "STRING", mode = "NULLABLE" },
    { name = "scheduled_arrival_time", type = "STRING", mode = "NULLABLE" },
    { name = "scheduled_travel_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "geom", type = "GEOGRAPHY", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "trip_updates_raw" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.rt.dataset_id
  table_id                 = "trip_updates_raw"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "feed_timestamp"
  }

  schema = jsonencode([
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "ingestion_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "source_url", type = "STRING", mode = "NULLABLE" },
    { name = "snapshot_uri", type = "STRING", mode = "NULLABLE" },
    { name = "entity_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "payload_bytes", type = "INTEGER", mode = "NULLABLE" },
    { name = "feed_date", type = "DATE", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "stop_updates" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.rt.dataset_id
  table_id                 = "stop_updates"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  clustering               = ["route_id", "trip_id", "stop_id"]
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "feed_timestamp"
  }

  schema = jsonencode([
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "trip_id", type = "STRING", mode = "NULLABLE" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "start_date", type = "DATE", mode = "NULLABLE" },
    { name = "stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "stop_sequence", type = "INTEGER", mode = "NULLABLE" },
    { name = "arrival_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "departure_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "predicted_arrival_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "predicted_departure_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "schedule_relationship", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "edge_delay_state" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.rt.dataset_id
  table_id                 = "edge_delay_state"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  clustering               = ["route_id", "trip_id", "edge_id"]
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "feed_timestamp"
  }

  schema = jsonencode([
    { name = "edge_id", type = "STRING", mode = "REQUIRED" },
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "trip_id", type = "STRING", mode = "NULLABLE" },
    { name = "scheduled_travel_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "rt_travel_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "edge_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "src_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "dst_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "is_delayed", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "updated_at", type = "TIMESTAMP", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "bottlenecks" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.analytics.dataset_id
  table_id                 = "bottlenecks"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  clustering               = ["route_id", "stop_id", "edge_id"]
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "feed_timestamp"
  }

  schema = jsonencode([
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "edge_id", type = "STRING", mode = "NULLABLE" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "affected_downstream_stops", type = "INTEGER", mode = "NULLABLE" },
    { name = "cumulative_downstream_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "avg_delay_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "max_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "bottleneck_score", type = "FLOAT", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "current_network" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.serving.dataset_id
  table_id            = "current_network"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels
  clustering          = ["route_id", "trip_id", "edge_id"]

  schema = jsonencode([
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "route_name", type = "STRING", mode = "NULLABLE" },
    { name = "route_type", type = "INTEGER", mode = "NULLABLE" },
    { name = "mode", type = "STRING", mode = "NULLABLE" },
    { name = "trip_id", type = "STRING", mode = "NULLABLE" },
    { name = "edge_id", type = "STRING", mode = "NULLABLE" },
    { name = "direction_id", type = "STRING", mode = "NULLABLE" },
    { name = "src_stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "dst_stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "src_stop_name", type = "STRING", mode = "NULLABLE" },
    { name = "dst_stop_name", type = "STRING", mode = "NULLABLE" },
    { name = "src_stop_sequence", type = "INTEGER", mode = "NULLABLE" },
    { name = "dst_stop_sequence", type = "INTEGER", mode = "NULLABLE" },
    { name = "stop_position", type = "INTEGER", mode = "NULLABLE" },
    { name = "scheduled_travel_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "rt_travel_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "edge_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "previous_edge_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "delay_delta_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "rolling_mean_delay_15m", type = "FLOAT", mode = "NULLABLE" },
    { name = "rolling_max_delay_30m", type = "INTEGER", mode = "NULLABLE" },
    { name = "downstream_delay_score", type = "INTEGER", mode = "NULLABLE" },
    { name = "affected_downstream_stops", type = "INTEGER", mode = "NULLABLE" },
    { name = "avg_edge_delay_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "src_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "dst_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "is_delayed", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "trip_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "data_stale", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "src_stop_lat", type = "FLOAT", mode = "NULLABLE" },
    { name = "src_stop_lon", type = "FLOAT", mode = "NULLABLE" },
    { name = "dst_stop_lat", type = "FLOAT", mode = "NULLABLE" },
    { name = "dst_stop_lon", type = "FLOAT", mode = "NULLABLE" },
    { name = "geom", type = "GEOGRAPHY", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "current_bottlenecks" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.serving.dataset_id
  table_id            = "current_bottlenecks"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels
  clustering          = ["route_id", "stop_id", "edge_id"]

  schema = jsonencode([
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "rank", type = "INTEGER", mode = "NULLABLE" },
    { name = "stop_id", type = "STRING", mode = "NULLABLE" },
    { name = "edge_id", type = "STRING", mode = "NULLABLE" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "affected_downstream_stops", type = "INTEGER", mode = "NULLABLE" },
    { name = "cumulative_downstream_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "avg_delay_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "max_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "bottleneck_score", type = "FLOAT", mode = "NULLABLE" },
    { name = "data_stale", type = "BOOLEAN", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "segment_risk" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.serving.dataset_id
  table_id            = "segment_risk"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels
  clustering          = ["route_id", "edge_id", "risk_label"]

  schema = jsonencode([
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "edge_id", type = "STRING", mode = "NULLABLE" },
    { name = "direction_id", type = "STRING", mode = "NULLABLE" },
    { name = "risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "risk_label", type = "STRING", mode = "NULLABLE" },
    { name = "threshold_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "current_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "previous_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "current_edge_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "previous_edge_delay_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "delay_delta_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "rolling_mean_delay_15m", type = "FLOAT", mode = "NULLABLE" },
    { name = "rolling_max_delay_30m", type = "INTEGER", mode = "NULLABLE" },
    { name = "downstream_delay_score", type = "INTEGER", mode = "NULLABLE" },
    { name = "affected_downstream_stops", type = "INTEGER", mode = "NULLABLE" },
    { name = "model_roc_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "baseline_roc_auc", type = "FLOAT", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "current_feed_health" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.serving.dataset_id
  table_id            = "current_feed_health"
  deletion_protection = var.bigquery_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "last_successful_update", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "data_stale", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "message", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "prediction_monitoring" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.monitoring.dataset_id
  table_id                 = "prediction_monitoring"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  clustering               = ["model_version"]
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "logged_at"
  }

  schema = jsonencode([
    { name = "logged_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "generated_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "feed_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "model_version", type = "STRING", mode = "NULLABLE" },
    { name = "prediction_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "network_edge_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "missing_prediction_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "avg_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "min_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "max_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "avg_model_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "top_50_avg_risk_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "high_risk_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "medium_or_high_risk_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "avg_current_delay_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "max_current_delay_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "delayed_edge_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "model_roc_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "baseline_roc_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_pr_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "baseline_pr_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_precision", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_recall", type = "FLOAT", mode = "NULLABLE" },
    { name = "positive_rate", type = "FLOAT", mode = "NULLABLE" },
    { name = "training_rows", type = "FLOAT", mode = "NULLABLE" },
    { name = "train_window", type = "STRING", mode = "NULLABLE" },
    { name = "test_window", type = "STRING", mode = "NULLABLE" },
    { name = "threshold_seconds", type = "FLOAT", mode = "NULLABLE" },
    { name = "prediction_horizon_minutes", type = "FLOAT", mode = "NULLABLE" },
    { name = "snapshot_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "first_snapshot", type = "STRING", mode = "NULLABLE" },
    { name = "latest_snapshot", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "retraining_runs" {
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.monitoring.dataset_id
  table_id                 = "retraining_runs"
  deletion_protection      = var.bigquery_deletion_protection
  labels                   = local.common_labels
  clustering               = ["status", "promoted"]
  require_partition_filter = true

  time_partitioning {
    type  = "DAY"
    field = "started_at"
  }

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "started_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "completed_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "message", type = "STRING", mode = "NULLABLE" },
    { name = "snapshot_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "first_snapshot", type = "STRING", mode = "NULLABLE" },
    { name = "latest_snapshot", type = "STRING", mode = "NULLABLE" },
    { name = "stop_update_rows", type = "INTEGER", mode = "NULLABLE" },
    { name = "training_rows", type = "INTEGER", mode = "NULLABLE" },
    { name = "positive_rate", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_roc_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "baseline_roc_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_pr_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "baseline_pr_auc", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_precision", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_recall", type = "FLOAT", mode = "NULLABLE" },
    { name = "model_f1", type = "FLOAT", mode = "NULLABLE" },
    { name = "threshold_seconds", type = "INTEGER", mode = "NULLABLE" },
    { name = "threshold_probability", type = "FLOAT", mode = "NULLABLE" },
    { name = "prediction_horizon_minutes", type = "INTEGER", mode = "NULLABLE" },
    { name = "embargo_minutes", type = "INTEGER", mode = "NULLABLE" },
    { name = "train_window", type = "STRING", mode = "NULLABLE" },
    { name = "test_window", type = "STRING", mode = "NULLABLE" },
    { name = "model_uri", type = "STRING", mode = "NULLABLE" },
    { name = "metrics_uri", type = "STRING", mode = "NULLABLE" },
    { name = "training_data_uri", type = "STRING", mode = "NULLABLE" },
    { name = "promoted", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "promoted_model_uri", type = "STRING", mode = "NULLABLE" },
    { name = "promoted_metrics_uri", type = "STRING", mode = "NULLABLE" },
  ])
}
