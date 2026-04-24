## `destroy_all_aws.py` — what it destroys (step-by-step)

This doc describes **exactly what** [`destroy_all_aws.py`](destroy_all_aws.py) destroys, in what **order**, and the important safety behaviors (bucket emptying, skip rules, and what is *not* removed).

Companion docs:
- **CLI flags**: [`aws/README.md`](README.md)
- **Master checklist & dependency order**: [`docs/6_aws-deployment.md`](../docs/6_aws-deployment.md)
- **Post-destroy validation**: [`validate_destroy_aws.py`](validate_destroy_aws.py)

---

## What this script does (high level)

At a high level, `aws/destroy_all_aws.py` is an **orchestrator** that tears down (most of) the Terraform-managed AWS stacks in a **safe reverse dependency order**, with a couple of special behaviors to avoid common teardown failures and preserve the Researcher App Runner service.

### Terraform destroys (in order)

By default it processes stacks in this order:

- **`terraform/8_enterprise`**: CloudWatch dashboards/alarms/extras
- **`terraform/7_frontend`**: CloudFront + S3 static site + API Gateway + `alex-api` Lambda + IAM  
  - *extra:* empties the frontend S3 bucket first (best-effort)
- **`terraform/6_agents`**: SQS + 5 agent Lambdas + IAM + S3 lambda-packages bucket
- **`terraform/5_database`**: Aurora + Secrets Manager secret + networking bits
- **`terraform/4_researcher`**: **special case** (see below)
- **`terraform/3_ingestion`**: ingest Lambda + API Gateway + API key resources + IAM
- **`terraform/2_sagemaker`**: SageMaker embedding endpoint + IAM

### Special case: `4_researcher` (App Runner is paused, not deleted)

By default, the script **does not destroy** `terraform/4_researcher`. Instead it:

- prints a **CAPS notice** that App Runner is being preserved and reminds you about the April 30th constraint,
- attempts `aws apprunner pause-service` for `alex-researcher`, and
- **skips** `terraform destroy` for that stack.

If you do want to fully remove the Researcher stack, run:

```bash
cd aws
uv run python destroy_all_aws.py --yes --destroy-researcher-terraform
```

### What this script does not remove

- **S3 Vector buckets + indexes** (console-only in this repo)
- **Third-party vendor configuration** (Clerk / OpenAI / Polygon keys)
- **App Runner `alex-researcher`** (by default): the service remains in AWS in a **paused** state; `validate_destroy_aws.py` may still report it as present until you delete it manually or run destroy with **`--destroy-researcher-terraform`**.

So in one sentence: it’s **Terraform teardown in reverse order + best-effort bucket emptying + App Runner pause/skip for Researcher**, with a validation script available afterward.

---

## Summary table (what gets removed)

| Stack id | Terraform directory | What gets destroyed (high-level) | Extra behavior |
| --- | --- | --- | --- |
| `8_enterprise` | `terraform/8_enterprise` | CloudWatch dashboards/alarms/extras | none |
| `7_frontend` | `terraform/7_frontend` | CloudFront, S3 static site bucket + policy, API Gateway, `alex-api` Lambda, IAM | **Empties the frontend S3 bucket first** (best-effort) |
| `6_agents` | `terraform/6_agents` | SQS queue + DLQ, 5 agent Lambdas, IAM, S3 lambda packages bucket | none |
| `5_database` | `terraform/5_database` | Aurora cluster/instances, DB secret, SG/subnets as defined | none |
| `4_researcher` | `terraform/4_researcher` | **Default:** App Runner **not** deleted — script runs **`aws apprunner pause-service`** (best-effort) and **skips** `terraform destroy` for this stack. With **`--destroy-researcher-terraform`**: full destroy (App Runner + ECR + scheduler, etc.). | Prints a **CAPS** notice about App Runner / April 30th; optional Terraform destroy only with flag |
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

### Special case: `4_researcher` (App Runner — pause, do not delete by default)

For stack **`4_researcher`**, the default behavior is:

1. Print a **CAPS** banner (see script) explaining that **App Runner is not deleted** and that **(re)deploy may not be possible after April 30th** — **pause manually in the console** if `pause-service` fails.
2. Resolve the service ARN from `terraform output -raw app_runner_service_id`, or from `aws apprunner list-services` (service name **`alex-researcher`**).
3. Run **`aws apprunner pause-service --service-arn …`** (best-effort).
4. **Skip** `terraform destroy` in `terraform/4_researcher` so the service definition and Terraform state remain.

To **fully destroy** the Researcher stack (including App Runner), run destroy with **`--destroy-researcher-terraform`** (see [`aws/README.md`](README.md) CLI table).

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
4_researcher (default)   (pause App Runner; SKIP terraform destroy)
   |                        (--destroy-researcher-terraform → full Terraform destroy)
   v
Terraform: 3_ingestion   (ingest Lambda + API Gateway + API key + IAM)
   |
   v
Terraform: 2_sagemaker   (embedding endpoint)
```

---

## After destroy — validate nothing is left

Use the post-destroy validator:

```bash
cd aws
uv run python validate_destroy_aws.py
```

This checks (read-only) for commonly named Alex resources still present (Lambdas, SQS, Aurora, SageMaker endpoint, S3 buckets, ECR, App Runner, API Gateway, CloudFront by comment, EventBridge, CloudWatch dashboards).

If you used the **default** `4_researcher` behavior (pause, no Terraform destroy), a **paused** App Runner service may still appear — that is expected until you remove it or pass **`--destroy-researcher-terraform`** on a targeted destroy of `4_researcher`.

---

## Cost note

Even after destroy succeeds, it’s normal for **billing data** to lag. Always verify in:
- AWS Billing / Bills
- Cost Explorer

