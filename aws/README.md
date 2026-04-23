# AWS orchestration (`aws/`)

Full-stack automation for Alex lives here and in [`docs/6_aws-deployment.md`](../docs/6_aws-deployment.md).

**One command** (`deploy_all_aws.py`) runs the **full automated sequence** (Terraform **2 → 8**, packaging, DB migrations, then `scripts/deploy.py` for Part 7) with **logged** commands and **`terraform output`** after each apply.

Terraform **cannot** create **S3 Vector** buckets (Guide 3); the script **pauses** there so you can confirm console work—or pass **`--skip-vectors-prompt`** if the vector bucket + index **already exist**. **`destroy_all_aws.py --yes`** tears down **all Terraform stacks** in safe order (not S3 Vector buckets).

---

## `scripts/` — Guide 7 only

**No.** In `scripts/` you only have **Guide 7–scoped** helpers. They **do not** deploy or destroy SageMaker, ingest, researcher, database, agents, or enterprise stacks.

| Script | Role | Same as full deploy/teardown? |
| --- | --- | --- |
| [`scripts/deploy.py`](../scripts/deploy.py) | Packages `backend/api`, runs `terraform/7_frontend`, builds Next.js, uploads `frontend/out/` to S3, invalidates CloudFront. | **No** — only **Part 7** (frontend + API). |
| [`scripts/destroy.py`](../scripts/destroy.py) | Empties the Part 7 frontend S3 bucket, runs `terraform destroy` in `terraform/7_frontend`, removes some local build artifacts. | **No** — only **Part 7** teardown. |

---

## S3 Vectors (manual in AWS) — what the deploy script does

**You must create the S3 *Vector* bucket and index yourself** in the AWS Console. This repo’s Terraform does **not** provision vector buckets (they live under S3 → **Vector buckets**, not a normal S3 bucket).

When `deploy_all_aws.py` reaches the **`vectors`** step, it will:

1. **Print** that you need the console and point you at **[`guides/3_ingest.md`](../guides/3_ingest.md)** (same steps as the guide: create vector bucket, create index, naming like `alex-vectors-<account-id>`, index `financial-research`, dimension **384**, metric **Cosine**, etc.).
2. **Remind** you to put **`VECTOR_BUCKET`** (and related values) in the root **`.env`** and in **`terraform/6_agents/terraform.tfvars`** as the guide describes before later steps need them.
3. **Wait** in the terminal until you press **Enter** (that is your “continue”: there is no separate UI button—it is normal stdin after you finish in the browser).

After you press **Enter**, the script moves on to **ingest** (package + `terraform/3_ingestion`).

**Re-runs / automation:** If the vector bucket and index **already exist**, start deploy with **`--skip-vectors-prompt`** so the script does **not** wait for Enter on that step.

---

## What was added: `aws/` orchestration

| File | Purpose |
| --- | --- |
| [`deploy_all_aws.py`](deploy_all_aws.py) | End-to-end **deploy** aligned with `docs/6_aws-deployment.md`: Terraform **2 → 8_enterprise** (by steps), `uv run` for ingest / researcher / DB / agents, then **`scripts/deploy.py`** for **Guide 7** (step id `part7`). Prints each command and **`terraform output -json`** after each apply. **`--sleep`** (default **15s**) between most steps. |
| [`destroy_all_aws.py`](destroy_all_aws.py) | End-to-end **destroy** for Terraform stacks **`8_enterprise` → `2_sagemaker`**, with **`--sleep`** (default **5s**). Empties the Part 7 frontend bucket before destroying `7_frontend` (same idea as `scripts/destroy.py`). Requires **`--yes`**. |
| [`test_all_aws.py`](test_all_aws.py) | **Read-only smoke test** after deploy (Terraform outputs + `aws` CLI). Optional stack **`8_enterprise`** is **SKIP** if not deployed. |
| [`orchestrator.py`](orchestrator.py) | Shared `terraform init` / `apply` / `destroy`, output printing, S3 empty helper. |
| [`pyproject.toml`](pyproject.toml) + [`uv.lock`](uv.lock) | Small **uv** project so you run everything with **`uv run`** from `aws/`. |
| This **README** | How to run + comparison tables. |

---

## Commands

From this directory:

```bash
cd aws && uv sync
uv run python deploy_all_aws.py --help
uv run python deploy_all_aws.py --sleep 20
uv run python deploy_all_aws.py --skip-vectors-prompt --sleep 20
uv run python destroy_all_aws.py --dry-run
uv run python destroy_all_aws.py --yes
uv run python test_all_aws.py
uv run python test_all_aws.py --fail-fast
```

**Part 7** (frontend + API + upload) is still implemented in **`scripts/deploy.py`**; `deploy_all_aws.py` invokes it as step **`part7`** (Guide 7 in the course tables).

---

## After `deploy_all_aws.py` — what you should see

When the sequence includes **`part7`** (runs `scripts/deploy.py`), **`terraform/7_frontend`** outputs include:

| Output | Meaning |
| --- | --- |
| **`cloudfront_url`** | **Public Alex app** — `https://….cloudfront.net` (Next.js static site + `/api/*` routed to API Gateway). Open this in a browser. |
| **`api_gateway_url`** | Direct HTTP API URL (the UI normally talks to **`/api/*` on CloudFront**, not this host directly). |
| **`s3_bucket_name`** | Bucket holding the exported `frontend/out/` files. |

**Expect:** Clerk sign-in, then dashboard / accounts / advisor flows per [`guides/7_frontend.md`](../guides/7_frontend.md). CloudFront can take **several minutes** after first creation. **`deploy_all_aws.py`** prints a short **“what to expect”** block at the end when `part7` ran.

You still need the **S3 Vectors** bucket (Guide 3) before ingest/agents can use vectors; the smoke test reminds you about vectors.

---

## Partial runs

| Script | Flags |
| --- | --- |
| `deploy_all_aws.py` | **`--from-step`** / **`--to-step`** — step ids: `sagemaker`, `vectors`, `ingest`, `researcher-partial`, `researcher-image`, `researcher-full`, `database`, `db-migrate`, `agents`, `part7`, `enterprise`. Optional **`--run-8b`** after `agents` runs `deploy_all_lambdas.py`. |
| `destroy_all_aws.py` | **`--from-stack`** / **`--to-stack`** — stack ids `8_enterprise`, `7_frontend`, `6_agents`, `5_database`, `4_researcher`, `3_ingestion`, `2_sagemaker` (e.g. only `7_frontend`). |

Use **`deploy_all_aws.py --dry-run`** or **`destroy_all_aws.py --dry-run`** to list what would run (destroy dry-run does **not** require `--yes`).

---

## Related doc

| Doc | Content |
| --- | --- |
| [`docs/6_aws-deployment.md`](../docs/6_aws-deployment.md) | Master tables, dependency order, manual console steps, and how `aws/` relates to `scripts/`. |
