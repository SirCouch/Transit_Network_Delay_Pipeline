terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
}

variable "project_id" {
  description = "Dedicated GCP project ID."
  type        = string
}

variable "region" {
  description = "Primary region for regional GCP resources."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"
}

locals {
  app_name = "transit-delay"

  labels = {
    app         = local.app_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# This file is a readable shape of the real system, not a replacement for
# infra/terraform. The blocks below are intentionally minimal.

resource "google_storage_bucket" "raw_feeds" {
  name                        = "${var.project_id}-${local.app_name}-raw"
  location                    = "US-CENTRAL1"
  uniform_bucket_level_access = true
  labels                      = local.labels
}

resource "google_bigquery_dataset" "transit" {
  dataset_id = "transit_delay_${var.environment}"
  location   = "US"
  labels     = local.labels
}

resource "google_service_account" "pipeline" {
  account_id   = "${local.app_name}-pipeline"
  display_name = "Transit delay pipeline runtime"
}

resource "google_cloud_run_v2_job" "ingest" {
  name     = "${local.app_name}-ingest-${var.environment}"
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email

      containers {
        image = "us-docker.pkg.dev/cloudrun/container/hello"

        env {
          name  = "ENVIRONMENT"
          value = var.environment
        }
      }
    }
  }

  labels = local.labels
}

output "raw_bucket_name" {
  description = "Example raw feed bucket name."
  value       = google_storage_bucket.raw_feeds.name
}

output "dataset_id" {
  description = "Example BigQuery dataset ID."
  value       = google_bigquery_dataset.transit.dataset_id
}
