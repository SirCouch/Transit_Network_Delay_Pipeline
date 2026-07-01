locals {
  common_labels = merge(
    {
      app         = "transit-delay-pipeline"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.labels
  )

  raw_bucket_name = coalesce(var.raw_bucket_name, "${var.project_id}-gtfs-raw")

  dataset_ids = {
    static     = "gtfs_static"
    graph      = "gtfs_graph"
    rt         = "gtfs_rt"
    analytics  = "gtfs_analytics"
    serving    = "gtfs_serving"
    monitoring = "gtfs_monitoring"
  }

  services = {
    api             = "transit-api"
    dashboard       = "transit-dashboard"
    ingest          = "transit-ingest-job"
    serving_refresh = "transit-serving-refresh-job"
    retraining      = "transit-segment-risk-retraining-job"
  }
}
