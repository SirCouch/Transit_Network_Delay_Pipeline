terraform {
  required_version = ">= 1.6.0"
}

variable "project_name" {
  description = "Human-readable project name used to build example names."
  type        = string
  default     = "transit-delay"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "region" {
  description = "Example deployment region."
  type        = string
  default     = "us-central1"
}

variable "extra_labels" {
  description = "Additional labels to merge into the common label set."
  type        = map(string)
  default     = {}
}

locals {
  normalized_project_name = replace(lower(var.project_name), " ", "-")

  default_labels = {
    app         = local.normalized_project_name
    environment = var.environment
    managed_by  = "terraform"
  }

  labels = merge(local.default_labels, var.extra_labels)

  resource_prefix = "${local.normalized_project_name}-${var.environment}"
}

output "resource_prefix" {
  description = "A consistent name prefix built from variables and locals."
  value       = local.resource_prefix
}

output "region" {
  description = "The selected region."
  value       = var.region
}

output "labels" {
  description = "Merged labels that would be applied to resources."
  value       = local.labels
}
