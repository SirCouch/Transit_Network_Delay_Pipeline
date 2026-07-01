# Terraform Exercises

Use these in order. Start in `terraform-learning/00-hcl-basics`.

## 1. Change An Input

Run:

```powershell
terraform plan -var="environment=staging"
```

Notice how the output values change without editing files.

## 2. Edit A Variable Default

Open `00-hcl-basics/main.tf` and change `region` from `us-central1` to `us-east1`.

Run:

```powershell
terraform fmt
terraform validate
terraform plan
```

The lesson: defaults live in code, but command-line `-var` values can override them.

## 3. Add A Tag

In `00-hcl-basics/main.tf`, add a new entry to `default_labels`, such as:

```hcl
owner = "learning"
```

Run `terraform plan` and inspect the `labels` output.

The lesson: locals are computed values. They are useful for naming, tagging, and avoiding repeated expressions.

## 4. Create A Local File

Move to `01-local-file`.

Run:

```powershell
terraform init
terraform plan
terraform apply
```

Terraform will create `generated/terraform-note.txt`.

Then change `message` and run another plan. Terraform should show an update.

## 5. Destroy The Local File

From `01-local-file`, run:

```powershell
terraform destroy
```

The lesson: Terraform removes resources that are in state when you ask it to destroy.

## 6. Read The Real Project Shape

Compare `02-gcp-project-shape/main.tf` with files in `infra/terraform/`.

Look for these patterns:

- Variables define environment-specific inputs.
- Locals build consistent names and labels.
- Resources declare cloud objects.
- Outputs expose important values after deployment.
- IAM resources grant specific permissions to service accounts.

Do not copy the learning examples directly into production. Instead, use them to understand what the production files are doing.
