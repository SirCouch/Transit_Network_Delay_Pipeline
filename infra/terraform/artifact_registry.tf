resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repo_id
  description   = "Docker images for the transit delay pipeline"
  format        = "DOCKER"
  labels        = local.common_labels

  depends_on = [google_project_service.required]
}
