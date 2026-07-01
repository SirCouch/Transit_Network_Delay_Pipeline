# Terraform Learning Lab

This directory is a safe place to learn how Terraform works before changing the real infrastructure in `infra/terraform/`.

The main idea: Terraform turns `.tf` files into a plan, compares that plan with state, and then applies only the changes needed to make real infrastructure match the code.

## Mental Model

Terraform has four core pieces:

- **Configuration**: the `.tf` files you write.
- **Providers**: plugins that know how to manage a platform, such as Google Cloud.
- **State**: Terraform's record of what it created or manages.
- **Plan**: the proposed change from current state to desired configuration.

The usual workflow is:

```powershell
terraform init
terraform fmt
terraform validate
terraform plan
terraform apply
```

For this repository, do not run `terraform apply` in `infra/terraform/` until the GCP project, billing, quotas, and ignored private variables are ready.

## Learning Path

1. `00-hcl-basics/`
   Learn Terraform syntax without creating any cloud resources. This is the safest starting point.

2. `01-local-file/`
   Learn how a resource works by creating a local text file. This uses the `local` provider, so `terraform init` may download a provider plugin.

3. `02-gcp-project-shape/`
   Read a simplified GCP layout that matches this MBTA delay pipeline: storage, BigQuery, services, scheduler, and IAM. Treat it as a guided map, not deployment code.

4. `EXERCISES.md`
   Small tasks to practice variables, locals, outputs, resources, and reading plans.

## How To Use The Examples

From one example directory:

```powershell
cd terraform-learning\00-hcl-basics
terraform init
terraform fmt
terraform validate
terraform plan
```

If you run `terraform apply` in an example, Terraform may create local state files such as `terraform.tfstate`. Those are ignored by git.

## Key File Types

- `main.tf`: common place for resources, locals, and outputs in small examples.
- `variables.tf`: input variable declarations.
- `outputs.tf`: values Terraform prints after plan or apply.
- `terraform.tfvars`: private local values. Do not commit this file.
- `terraform.tfvars.example`: safe sample values that can be committed.
- `.terraform/`: downloaded provider plugins and module cache. Do not commit this directory.

## How This Relates To This Repo

The production infrastructure lives in `infra/terraform/`. That directory manages GCP resources for:

- BigQuery datasets and tables.
- Cloud Run jobs and services.
- Cloud Scheduler triggers.
- Service accounts and IAM.
- Storage buckets.
- Artifact Registry.
- Budget controls.

Use this learning directory to practice the Terraform language and workflow. Use `infra/terraform/` only when you are ready to work on the actual deployment.
