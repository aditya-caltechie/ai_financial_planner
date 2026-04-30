# AWS orchestration (`aws/`)

This directory contains the scripts that orchestrate an end-to-end deploy/destroy of the AWS infrastructure for this repo, plus validation utilities.

## What’s in here

| File | Purpose |
| --- | --- |
| [`deploy_all_aws.py`](deploy_all_aws.py) | End-to-end **deploy** pipeline (Terraform stacks + packaging + DB migrate + optional frontend/API deploy). Supports `--from-step` / `--to-step` and `--dry-run`. |
| [`destroy_all_aws.py`](destroy_all_aws.py) | End-to-end **destroy** pipeline in safe reverse order. Requires `--yes`. Supports `--dry-run`. |
| [`validate_deploy_aws.py`](validate_deploy_aws.py) | **Read-only** post-deploy checks (Terraform outputs + AWS CLI). |
| [`validate_destroy_aws.py`](validate_destroy_aws.py) | **Read-only** post-destroy checks (AWS CLI). |
| [`orchestrator.py`](orchestrator.py) | Shared Terraform runner helpers and utilities (including S3 empty). |
| [`pyproject.toml`](pyproject.toml) + [`uv.lock`](uv.lock) | `uv` project so you can run everything via `uv run`. |

## Quick start

From the repo root:

```bash
cd aws && uv sync

# Deploy
uv run deploy_all_aws.py --sleep 20
uv run validate_deploy_aws.py

# Destroy
uv run destroy_all_aws.py --yes
uv run validate_destroy_aws.py
```

## Deploy pipeline overview

`deploy_all_aws.py` is designed to be **re-runnable**. If something fails part-way through, re-run with a narrower range.

### Step ids

`--from-step` / `--to-step` accept:

`sagemaker`, `vectors`, `ingest`, `researcher-partial`, `researcher-image`, `researcher-full`, `database`, `db-migrate`, `agents`, `part7`, `enterprise`

To see the exact order without deploying anything:

```bash
cd aws
uv run deploy_all_aws.py --dry-run
```

### Resuming after a failure

Example: resume from DB migration through the end:

```bash
cd aws
uv run deploy_all_aws.py --from-step db-migrate --to-step enterprise
```

## S3 Vectors (manual console step)

S3 Vector buckets and indexes are created in the AWS Console (not by Terraform in this repo).

When the deploy pipeline reaches the `vectors` step it will:

1. Print what you need to create in the console (vector bucket + index)
2. Remind you to set the required env/config values (for example `VECTOR_BUCKET`)
3. Wait for **Enter** to continue (unless you pass `--skip-vectors-prompt`)

If the vector bucket/index already exist, use:

```bash
cd aws
uv run deploy_all_aws.py --skip-vectors-prompt
```

## Frontend + API deploy (`part7`)

The deploy pipeline’s `part7` step invokes `scripts/deploy.py` (frontend build/export + upload + API infra).

After `part7`, `terraform/7_frontend` outputs typically include:

| Output | Meaning |
| --- | --- |
| `cloudfront_url` | Public app URL (`https://...cloudfront.net`) |
| `api_gateway_url` | Direct API Gateway URL (CloudFront usually routes `/api/*` to it) |
| `s3_bucket_name` | Bucket containing the exported `frontend/out/` assets |

CloudFront may take several minutes to fully propagate on first creation.

## Destroy behavior notes

- `destroy_all_aws.py` destroys Terraform stacks in reverse order (8 → 2).
- It empties the frontend bucket before destroying `terraform/7_frontend`.
- For `terraform/4_researcher`, it **pauses** the App Runner service by default and **skips** `terraform destroy` unless you pass `--destroy-researcher-terraform`.
- S3 Vector buckets/indexes are **not** deleted by these scripts.

## Troubleshooting

### Analysis is “stuck” (job stays `pending`)

Most common cause: `terraform/5_database` was re-applied and produced a **new** Secrets Manager ARN, but `terraform/6_agents` is still configured with the old `aurora_secret_arn`, so the Planner fails immediately.

Fix (recommended):

```bash
cd aws
uv run deploy_all_aws.py --from-step agents --to-step agents
```

### Validate deploy vs validate destroy

- Use `validate_deploy_aws.py` after deploy.
- Use `validate_destroy_aws.py` after destroy.

If you deployed outside your default region, pass `--region` to `validate_destroy_aws.py`.

## Credentials

All scripts rely on your configured AWS CLI credentials (same as manual Terraform). At startup, the tool check prints `aws sts get-caller-identity` so you can confirm which identity is being used.

