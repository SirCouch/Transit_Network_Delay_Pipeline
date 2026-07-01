resource "google_storage_bucket" "raw_feeds" {
  name                        = local.raw_bucket_name
  project                     = var.project_id
  location                    = var.storage_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  lifecycle_rule {
    condition {
      age            = 14
      matches_prefix = ["realtime/trip_updates/"]
    }

    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}
