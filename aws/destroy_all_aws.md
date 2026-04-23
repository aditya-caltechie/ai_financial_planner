## `destroy_all_aws.py` — what it destroys (step-by-step)

This doc describes **exactly what** [`destroy_all_aws.py`](destroy_all_aws.py) destroys, in what **order**, and the important safety behaviors (bucket emptying, skip rules, and what is *not* removed).

Companion docs:
- **CLI flags**: [`aws/README.md`](README.md)
- **Master checklist & dependency order**: [`docs/6_aws-deployment.md`](../docs/6_aws-deployment.md)
- **Post-destroy validation**: [`validate_destroy_aws.py`](validate_destroy_aws.py)

---

## Big picture

`destroy_all_aws.py` iterates Terraform stacks in a fixed **reverse** order (dependent / expensive stacks first):

```
  → 8_enterprise
  → 7_frontend
  → 6_agents
  → 5_database
  → 4_researcher
  → 3_ingestion
  → 2_sagemaker
```

You can slice this chain using `--from-stack` / `--to-stack`, but the order is always preserved.

---

## Summary table (what gets removed)

| Stack id | Terraform directory | What gets destroyed (high-level) | Extra behavior |
| --- | --- | --- | --- |
| `8_enterprise` | `terraform/8_enterprise` | CloudWatch dashboards/alarms/extras | none |
| `7_frontend` | `terraform/7_frontend` | CloudFront, S3 static site bucket + policy, API Gateway, `alex-api` Lambda, IAM | **Empties the frontend S3 bucket first** (best-effort) |
| `6_agents` | `terraform/6_agents` | SQS queue + DLQ, 5 agent Lambdas, IAM, S3 lambda packages bucket | none |
| `5_database` | `terraform/5_database` | Aurora cluster/instances, DB secret, SG/subnets as defined | none |
| `4_researcher` | `terraform/4_researcher` | App Runner service, ECR repo, scheduler lambda/rule/role (if created) | none |
| `3_ingestion` | `terraform/3_ingestion` | ingest Lambda, API Gateway, API key resources, IAM, related buckets | none |
| `2_sagemaker` | `terraform/2_sagemaker` | SageMaker endpoint/model/config and role/policies | none |

---

## Detailed behavior (what the script does)

### Safety gate: `--yes`

The script refuses to run unless you pass **`--yes`**.

### Per-stack rules (skip logic)

For each stack directory, it will:

1. Print a stack banner.
2. If the stack is `7_frontend`, attempt to empty the S3 bucket first.
3. If `terraform.tfvars` is missing, it prints a warning and **skips** that stack.
4. If `.terraform/` is missing, it prints a warning and **skips** that stack.
5. Best-effort prints `terraform output -json` (if available).
6. Runs `terraform init -input=false`, then `terraform destroy -input=false -auto-approve`.

### Special case: emptying the Part 7 frontend bucket

Before destroying `terraform/7_frontend`, the script tries to:

1. Read the bucket name from `terraform output -raw s3_bucket_name`.
2. Run `aws s3 rm s3://<bucket>/ --recursive`.

This is a best-effort cleanup to avoid “bucket not empty” delete failures.

---

## ASCII flow (destroy)

```
Terraform: 8_enterprise  (dashboards)
   |
   v
Terraform: 7_frontend    (pre-empty S3 bucket → destroy CloudFront/S3/API/Lambda/IAM)
   |
   v
Terraform: 6_agents      (SQS + agent Lambdas + IAM + S3 lambda packages bucket)
   |
   v
Terraform: 5_database    (Aurora + Secrets)
   |
   v
Terraform: 4_researcher  (App Runner + ECR + optional scheduler)
   |
   v
Terraform: 3_ingestion   (ingest Lambda + API Gateway + API key + IAM)
   |
   v
Terraform: 2_sagemaker   (embedding endpoint)
```

---

## What this script does **not** destroy

The script prints reminders at the end; the key items are:

- **S3 Vector buckets + indexes** (Guide 3): **manual console cleanup**. These are not Terraform-managed in this repo.
- **Third-party vendors** (Clerk / OpenAI / Polygon): keys remain in vendor dashboards.

---

## After destroy — validate nothing is left

Use the post-destroy validator:

```bash
cd aws
uv run python validate_destroy_aws.py
```

This checks (read-only) for commonly named Alex resources still present (Lambdas, SQS, Aurora, SageMaker endpoint, S3 buckets, ECR, App Runner, API Gateway, CloudFront by comment, EventBridge, CloudWatch dashboards).

---

## Cost note

Even after destroy succeeds, it’s normal for **billing data** to lag. Always verify in:
- AWS Billing / Bills
- Cost Explorer

