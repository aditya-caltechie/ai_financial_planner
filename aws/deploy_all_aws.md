## `deploy_all_aws.py` — what it deploys (step-by-step)

This doc describes **exactly what** [`deploy_all_aws.py`](deploy_all_aws.py) deploys, in what **sequence**, and which parts are **Terraform** vs **packaging / manual** steps.

It is a narrative companion to:
- **Master checklist**: [`docs/6_aws-deployment.md`](../docs/6_aws-deployment.md)
- **CLI flags**: [`aws/README.md`](README.md)

**NOTE** :
- Make sure you are connected to Wired connection, else pushing image to ECR fails.
- Also must have S3 vector created and indexed manually.
---

## Big picture

`deploy_all_aws.py` runs a **fixed pipeline** of step ids (you can slice it with `--from-step` / `--to-step`):

```
  → sagemaker
  → vectors (manual console step; pause unless --skip-vectors-prompt)
  → ingest
  → researcher-partial
  → researcher-image
  → researcher-full
  → database
  → db-migrate
  → agents
  → part7
  → enterprise
```

### What “uses Terraform” means here

For Terraform-backed steps, the script calls:

- `terraform init -input=false`
- `terraform apply -input=false -auto-approve`
- `terraform output -json` (printed after apply)

**Each Terraform directory is independent** (local state under `terraform/<stack>/terraform.tfstate`) and requires a configured `terraform.tfvars`.

---

## Summary table (what gets created)

| Step id | What happens | Terraform directory (if any) | Main AWS resources created |
| --- | --- | --- | --- |
| `sagemaker` | Terraform apply | `terraform/2_sagemaker` | SageMaker serverless **embedding endpoint**, model/config, IAM role/policies |
| `vectors` | **Manual** in AWS console (Guide 3) | none | S3 **Vector** bucket + vector index (**not Terraform-managed**) |
| `ingest` | Package ingest zip, then Terraform apply | `terraform/3_ingestion` | Ingest **Lambda** + **API Gateway** + API key resources + IAM; also an S3 bucket named like `alex-vectors-<acct>` (used for some parts of the pipeline; S3 *Vector* buckets are separate) |
| `researcher-partial` | Terraform apply (targeted) | `terraform/4_researcher` | **ECR** repository + **App Runner IAM role** only (via `-target=...`) |
| `researcher-image` | Build/push container image | none | Docker build/push to **ECR** (image tag updates) |
| `researcher-full` | Terraform apply | `terraform/4_researcher` | **App Runner** service (and optional scheduler pieces if enabled in tfvars) |
| `database` | Terraform apply | `terraform/5_database` | **Aurora Serverless v2** cluster + secret (Secrets Manager), subnet group/SG/IAM as defined |
| `db-migrate` | Run DB scripts | none | No new AWS infra; uses **RDS Data API** to create schema + seed rows |
| `agents` | Package zips, then Terraform apply | `terraform/6_agents` | **SQS** queue + DLQ, 5 agent **Lambdas**, IAM, S3 `alex-lambda-packages-<acct>` bucket |
| `part7` | Delegate to course script | `terraform/7_frontend` (inside script) | **CloudFront** + S3 static hosting bucket + API Gateway + `alex-api` Lambda + IAM; uploads `frontend/out` and invalidates CF |
| `enterprise` | Terraform apply | `terraform/8_enterprise` | CloudWatch dashboards/alarms/enterprise extras (per guide) |

---

## Detailed sequence (what the script does)

### Step `sagemaker`

1. Runs `terraform apply` in `terraform/2_sagemaker`.
2. Prints outputs (e.g. endpoint name).

### Step `vectors` (manual)

1. Prints instructions pointing at `guides/3_ingest.md`.
2. **Pauses** for Enter so you can create:
   - S3 **Vector** bucket
   - Vector index
3. If you already did this, use `--skip-vectors-prompt` to avoid the pause.

### Step `ingest`

1. Packages the ingest lambda:
   - `cd backend/ingest && uv run package.py`
2. Applies Terraform:
   - `terraform apply` in `terraform/3_ingestion`

### Step `researcher-partial`

Applies a **targeted** Terraform apply (so an image can be pushed to an existing ECR repo):

- `terraform apply` in `terraform/4_researcher` with:
  - `-target=aws_ecr_repository.researcher`
  - `-target=aws_iam_role.app_runner_role`

### Step `researcher-image`

Build and push the Researcher container image:

- `cd backend/researcher && uv run deploy.py`

This uses Docker and pushes a linux/amd64 image to ECR.

### Step `researcher-full`

Applies the full `terraform/4_researcher` stack to create App Runner (and optional scheduling, if configured):

- `terraform apply` in `terraform/4_researcher`

### Step `database`

Applies the Aurora stack:

- `terraform apply` in `terraform/5_database`

### Step `db-migrate`

Runs database scripts in `backend/database`:

- `uv run test_data_api.py`
- `uv run run_migrations.py`
- `uv run seed_data.py`

Important behavior (re-deploy safety):
- The orchestration prefers **fresh ARNs from `terraform/5_database` outputs** and passes them as environment variables to these scripts.
- The database scripts load `.env` with `override=False` so `.env` **does not overwrite** explicit env vars passed by orchestration.

### Step `agents`

1. Packages agent zips using Docker:
   - `cd backend && uv run package_docker.py`
2. Applies the agent stack:
   - `terraform apply` in `terraform/6_agents`
3. Optional `--run-8b` runs:
   - `cd backend && uv run deploy_all_lambdas.py`

### Step `part7` (Guide 7)

Delegates to the course-provided deploy script:

- `cd scripts && uv run deploy.py`

That script handles:
- Packaging `backend/api` lambda zip
- Terraform apply in `terraform/7_frontend`
- Next.js build/export
- Upload to S3
- CloudFront invalidation

### Step `enterprise` (optional)

Applies the enterprise stack:

- `terraform apply` in `terraform/8_enterprise`

---

## ASCII flow (deploy)

```
Terraform: 2_sagemaker
   |
   v
Manual: S3 Vector bucket + index (console)
   |
   v
Package ingest zip  ──► Terraform: 3_ingestion
   |
   v
Terraform (targeted): 4_researcher (ECR + IAM)
   |
   v
Docker build/push ──► ECR image
   |
   v
Terraform (full): 4_researcher (App Runner + optional scheduler)
   |
   v
Terraform: 5_database (Aurora + Secret)
   |
   v
DB scripts: migrations + seed (Data API)
   |
   v
Package agent zips ──► Terraform: 6_agents (SQS + 5 Lambdas + S3 bucket)
   |
   v
Guide 7 script ──► Terraform: 7_frontend + build/upload + CF invalidate
   |
   v
Terraform: 8_enterprise (dashboards/alarms)
```

---

## Re-running after a partial failure

If the pipeline fails part-way, you can continue from where it failed using the step ids:

```bash
cd aws
uv run python deploy_all_aws.py --dry-run
uv run python deploy_all_aws.py --from-step db-migrate --to-step enterprise
```

---

## Notes / caveats

- **S3 Vector buckets are not Terraform-managed** in this repo. They must be created in the console and are not created/destroyed by these scripts.
- `deploy_all_aws.py` prints:
  - the **planned step order** for the chosen slice
  - **start / end timestamps**
  - **per-step durations** and **total duration**

