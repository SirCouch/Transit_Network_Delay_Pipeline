terraform {
  required_version = ">= 1.6.0"

  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

variable "message" {
  description = "Message written into the generated local file."
  type        = string
  default     = "Terraform manages desired state from configuration."
}

variable "filename" {
  description = "Path for the generated file."
  type        = string
  default     = "generated/terraform-note.txt"
}

resource "local_file" "note" {
  filename = var.filename
  content  = "${var.message}\n"
}

output "generated_file" {
  description = "The file created by Terraform."
  value       = local_file.note.filename
}
