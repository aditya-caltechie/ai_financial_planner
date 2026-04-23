# AWS deployment and teardown (Alex)

This document summarizes **how to recreate Alex on AWS** using the course **Terraform stacks** and **non-Terraform steps** from the guides, in a safe order. It also documents **how to destroy resources to stop ongoing cost**.

**Source of truth:** the numbered guides in [`guides/`](../guides/) (`1_permissions.md` → `8_enterprise.md`). Use this file as a **checklist**; if anything disagrees with a guide, follow the guide.

---

## Figure A — How services fit together (architecture roles)

Use this mental model when deciding **create order** and **destroy order**. (Compare to the “enterprise / multi-agent” diagram in the course materials.)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ USER                                                                        │
│  Browser ──HTTPS──► CloudFront ──► S3 (static Next.js export)               │
│           └──auth──► Clerk (SaaS, not AWS)                                   │
│           └──/api/*► API Gateway ──► Lambda (FastAPI "alex-api")            │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                    JWT validate (JWKS) │  Data API + Secrets
                                        ▼
                              ┌─────────────────┐
                              │ Aurora Postgres │
                              │ (Serverless v2) │
                              └────────┬────────┘
                                       ▲
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        │  SQS "analysis jobs"         │  Agent Lambdas write         │
        ▼                              │  job + instrument rows       │
 ┌──────────────┐                       │                              │
 │ Planner      │──invoke──────────────┼──► Tagger / Reporter /        │
 │ (Lambda)     │   (async)            │     Charter / Retirement      │
 └──────┬───────┘                       │     (Lambdas + Bedrock)     │
        │                               │                              │
        └──────────────────────────────┴──────────────────────────────┘

Parallel research / knowledge pipeline (Guides 2–4):

 EventBridge (optional) ──► Scheduler Lambda ──► App Runner (Researcher + Bedrock)
                                                      │
                                                      └──► API Gateway (ingest) + API key
                                                                │
                                                                ▼
                                                         Ingest Lambda
                                                                │
                                    SageMaker (embeddings) ◄────┘
                                                                │
                                                                ▼
                                              S3 Vectors bucket (console; not regular S3)
```

**Bill impact (rough priority for “turn off spend”):**

1. **Aurora** (`terraform/5_database`) — usually the largest steady cost while the cluster exists.
2. **App Runner** (`terraform/4_researcher`) — always-on style service while deployed.
3. **SageMaker serverless endpoint** (`terraform/2_sagemaker`) — can incur cost when invoked; destroy when not needed.
4. **Bedrock** — usage-based (tokens); no single “destroy” resource beyond stopping calls.
5. **CloudFront + API Gateway + Lambdas + SQS** — typically small at dev scale; still tear down when finished.

---

## Figure B — Recommended **create** flow (dependencies)

```
Guide 1 (IAM) ──► not Terraform; do once per account / engineer

terraform/2_sagemaker (embeddings endpoint)
        │
        ├──► Console: S3 *Vectors* bucket + index  (Guide 3; not in terraform/3_ingestion)
        │
        └──► backend/ingest: uv run package.py
                    │
                    └──► terraform/3_ingestion (ingest Lambda + HTTP API + key)

terraform/4_researcher (ECR + IAM first, then image push, then full apply)
        │
        └──► backend/researcher: uv run deploy.py  (Docker → ECR → deploy)

terraform/5_database (Aurora + secrets)
        │
        └──► backend/database: migrations + seed  (uv run …)

backend: uv run package_docker.py   (agent zip artifacts)
        │
        └──► terraform/6_agents (SQS + agent Lambdas + policy wiring)
                    │
                    └──► optional: backend/deploy_all_lambdas.py  (re-sync zips / taint+apply)

terraform/7_frontend  **requires local state files**:
        ../5_database/terraform.tfstate
        ../6_agents/terraform.tfstate
        │
        ├──► backend/api: uv run package_docker.py   (if not using scripts/deploy.py)
        │
        └──► terraform apply OR scripts/deploy.py (packages API, applies 7, builds UI, uploads S3, invalidates CF)

terraform/8_enterprise (optional dashboards / monitoring extras)
```

---

## Figure C — Recommended **destroy** flow (cost + dependency safety)

Destroy **roughly reverse** of create. **Do Aurora early** if your goal is to stop the biggest bill.

```
terraform/8_enterprise     terraform destroy
        │
        ▼
terraform/7_frontend      terraform destroy  (or: cd scripts && uv run destroy.py — Part 7 only)
        │                 Note: destroy empties S3 bucket first in destroy.py path
        ▼
terraform/6_agents        terraform destroy   (SQS, agent Lambdas, lambda-packages S3, …)
        │
        ▼
terraform/5_database        terraform destroy   (⚠ deletes DB + secrets; biggest cost saver)
        │
        ▼
terraform/4_researcher      terraform destroy   (App Runner, ECR repo policy, scheduler, …)
        │
        ▼
terraform/3_ingestion       terraform destroy
        │
        ▼
terraform/2_sagemaker       terraform destroy

Manual / console (easy to forget):
  • S3 **Vector** bucket + index (Guide 3) — delete in AWS Console when no longer needed
  • IAM group/users from Guide 1 — optional cleanup
  • Clerk app — external; cancel/delete in Clerk dashboard if desired
```

**Why `7_frontend` before `5_database`:** `terraform/7_frontend` reads **local** `terraform_remote_state` from `../5_database/terraform.tfstate` and `../6_agents/terraform.tfstate`. If you delete the database state/stack while still needing to run Terraform in `7_frontend`, you can break `terraform plan/destroy` for Part 7. In practice: **finish destroying Part 7 while Part 5/6 state still exists**, then destroy 6 → 5.

---

## Part 0 — Global prerequisites

- **AWS CLI** configured (`aws sts get-caller-identity`).
- **Terraform** ≥ 1.5 (guides assume Terraform; `7_frontend` requires ≥ 1.0 in file).
- **uv** for all Python commands (`uv run …`), per project rules.
- **Docker Desktop** running when any guide says to build images or Lambda packages.
- **Node + npm** for frontend (Guide 7).

---

## Part 1 — Guide 1: permissions (no Terraform in `terraform/`)

Follow **[`guides/1_permissions.md`](../guides/1_permissions.md)**.

You are creating **IAM policies/groups** in the AWS Console (or your org’s process). Nothing in `terraform/1_*` exists in this repo.

---

## Part 2 — Guide 2: SageMaker embeddings (`terraform/2_sagemaker`)

From repo root:

```bash
cd terraform/2_sagemaker
cp terraform.tfvars.example terraform.tfvars   # edit aws_region
terraform init
terraform apply
terraform output
```

Update root **`.env`** with the SageMaker endpoint name (see guide output).

Optional test commands are in **[`guides/2_sagemaker.md`](../guides/2_sagemaker.md)**.

---

## Part 3 — Guide 3: S3 Vectors + ingest (`terraform/3_ingestion`)

### 3A — Vector bucket (console)

Guide 3 requires creating an **S3 Vector bucket** and **vector index** in the AWS Console (not the same as a normal S3 bucket). Follow **[`guides/3_ingest.md`](../guides/3_ingest.md)** Step 1.

### 3B — Package ingest Lambda

```bash
cd backend/ingest
uv run package.py
```

### 3C — Terraform (ingest API + Lambda)

```bash
cd ../../terraform/3_ingestion
cp terraform.tfvars.example terraform.tfvars   # set aws_region, sagemaker_endpoint_name, etc. per guide
terraform init
terraform apply
terraform output
```

Fetch the **API key value** using the `aws apigateway get-api-key …` command shown in the guide output, then put `ALEX_API_ENDPOINT`, `ALEX_API_KEY`, `VECTOR_BUCKET` into root **`.env`**.

---

## Part 4 — Guide 4: Researcher on App Runner (`terraform/4_researcher`)

1. Configure **`backend/researcher/server.py`** (region + Bedrock model) as described in the guide.
2. Terraform uses a **two-step** pattern (ECR + roles, then image, then full stack):

```bash
cd terraform/4_researcher
cp terraform.tfvars.example terraform.tfvars   # openai_api_key, alex_api_*, scheduler_enabled, …
terraform init
terraform apply -target=aws_ecr_repository.researcher -target=aws_iam_role.app_runner_role
```

3. Build and push the Docker image:

```bash
cd ../../backend/researcher
uv run deploy.py
```

4. Create App Runner + optional scheduler:

```bash
cd ../../terraform/4_researcher
terraform apply
terraform output
```

---

## Part 5 — Guide 5: Aurora (`terraform/5_database`) + schema

```bash
cd terraform/5_database
cp terraform.tfvars.example terraform.tfvars   # aws_region, capacities per guide
terraform init
terraform apply
terraform output
```

Put `AURORA_CLUSTER_ARN` and `AURORA_SECRET_ARN` into root **`.env`**.

Initialize schema + seed:

```bash
cd ../../backend/database
uv run test_data_api.py
uv run run_migrations.py
uv run seed_data.py
```

(Additional verification / reset commands are in the guide.)

---

## Part 6 — Guide 6: agent orchestra (`terraform/6_agents`)

### 6A — Local tests (recommended)

Per guide: in each agent directory, `uv run test_simple.py`; then `cd backend && uv run test_simple.py`.

### 6B — Package all agent Lambdas (Linux-compatible zips)

```bash
cd backend
uv run package_docker.py
```

### 6C — Terraform variables from Part 5 + Part 3 + `.env`

```bash
cd ../terraform/6_agents
cp terraform.tfvars.example terraform.tfvars
# Fill aurora_* from:  cd ../5_database && terraform output
# Fill vector_bucket, bedrock_*, sagemaker_endpoint, polygon_*, etc.
terraform init
terraform apply
terraform output
```

### 6D — Optional code refresh helper

```bash
cd ../../backend
uv run deploy_all_lambdas.py        # may taint + terraform apply in 6_agents (see script header)
```

Add `SQS_QUEUE_URL` to **`.env`** (from `terraform output` in `6_agents`).

---

## Part 7 — Guide 7: frontend + API (`terraform/7_frontend`)

**Important:** this stack reads **local Terraform state** from:

- `terraform/5_database/terraform.tfstate`
- `terraform/6_agents/terraform.tfstate`

So **apply `5_database` and `6_agents` on this machine** (or copy compatible state files) before Part 7.

### Option A — All-in-one script (recommended when Docker works)

From repo root:

```bash
cd scripts
uv sync
uv run deploy.py
```

`scripts/deploy.py` packages **`backend/api`**, runs **`terraform apply`** in `terraform/7_frontend`, builds the Next.js export with the production API URL, uploads to S3, and creates a CloudFront invalidation.

### Option B — Manual (matches guide spirit)

```bash
cd backend/api
uv run package_docker.py

cd ../../terraform/7_frontend
cp terraform.tfvars.example terraform.tfvars   # clerk_jwks_url, clerk_issuer, aws_region
terraform init
terraform apply
terraform output
```

Build frontend and upload (Guide 7 shows `npm run build` + `aws s3 sync out/` + invalidation). **`terraform apply` alone does not upload the static site**; the bucket stays empty until you sync `frontend/out/`.

---

## Part 8 — Guide 8: enterprise add-ons (`terraform/8_enterprise`)

Optional monitoring dashboards / extras per **[`guides/8_enterprise.md`](../guides/8_enterprise.md)**:

```bash
cd terraform/8_enterprise
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

---

## Destroy and cost control — command checklist

### Quick win (database off)

If you only pause one thing, destroy Aurora:

```bash
cd terraform/5_database
terraform destroy
```

### Destroy **everything** Terraform manages (typical full teardown)

Run from repo root in this order:

```bash
cd terraform/8_enterprise && terraform destroy
cd ../7_frontend && terraform destroy
cd ../6_agents && terraform destroy
cd ../5_database && terraform destroy
cd ../4_researcher && terraform destroy
cd ../3_ingestion && terraform destroy
cd ../2_sagemaker && terraform destroy
```

### Part 7 helper script

`scripts/destroy.py` only targets **`terraform/7_frontend`**: empties the frontend S3 bucket, runs `terraform destroy`, deletes local `frontend/out`, `.next`, and `backend/api/api_lambda.zip`.

```bash
cd scripts
uv run destroy.py
```

### Manual resources to delete (not covered by Terraform above)

- **S3 Vectors** bucket + indexes (Guide 3) — AWS Console.
- **Clerk** application keys / app — Clerk dashboard (not AWS billing, but good hygiene).
- **OpenAI API key** usage — revoke/rotate if you no longer need tracing.

---

## What this doc intentionally does **not** duplicate

- Exact **`terraform.tfvars`** field names per stack (they change slightly by guide) — always copy `terraform.tfvars.example` in each `terraform/*` directory.
- Bedrock **model access** steps — follow Guides 4 and 6 + AWS Console “Model access”.
- Debugging tables (VPC, IAM, CloudWatch) — use the troubleshooting sections inside each guide.

---

## Related reading in this repo

| Topic | Doc |
| --- | --- |
| Research → ingest → vectors narrative | [`docs/data-pipeline.md`](data-pipeline.md) |
| Broader architecture / costs | [`docs/3_architecture.md`](3_architecture.md) |
| Multi-agent collaboration diagram | [`docs/4_agent_architecture.md`](4_agent_architecture.md) |
| Course steps | [`guides/`](../guides/) |
