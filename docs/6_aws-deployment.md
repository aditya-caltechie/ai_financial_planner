# AWS deployment and teardown (Alex)

This document summarizes **how to recreate Alex on AWS** using the course **Terraform stacks** and **non-Terraform steps** from the guides, in a safe order. It also documents **how to destroy resources to stop ongoing cost**.

**Source of truth:** the numbered guides in [`guides/`](../guides/) (`1_permissions.md` → `8_enterprise.md`). Use this file as a **checklist**; if anything disagrees with a guide, follow the guide.

---

## Prerequisites (before Step 1 in the tables)

Hard dependencies for a smooth run:

| Prerequisite | Why |
| --- | --- |
| **AWS CLI** configured (`aws sts get-caller-identity`) | Terraform and scripts call AWS APIs. |
| **Terraform** installed (≥ 1.5 recommended) | All `terraform/*` stacks. |
| **Docker Desktop** running | Researcher image (`5b`) and agent/API Lambda packaging (`8`, `9` via `deploy.py`). |
| **uv** + **Node.js / npm** | All `uv run …` paths and Next.js build for Part 7. |
| **[Guide 1](../guides/1_permissions.md) IAM** complete | Your IAM user must be allowed to create the services below. |
| **Bedrock model access** in the console for the **regions** your code uses ([Guides 4](../guides/4_researcher.md) and [6](../guides/6_agents.md)) | Researcher + agent Lambdas call Bedrock. |
| **`OPENAI_API_KEY`** in root `.env` before **5b** | Required for OpenAI Agents SDK tracing in Researcher ([Guide 4](../guides/4_researcher.md)). |
| **`POLYGON_API_KEY`** (and plan) ready before **8** | Planner / agents use Polygon per [Guide 6](../guides/6_agents.md); set in `.env` and `terraform/6_agents/terraform.tfvars`. |
| **Clerk app + JWKS + issuer** before **9** | Set `clerk_jwks_url` / `clerk_issuer` in `terraform/7_frontend/terraform.tfvars` and keep Clerk keys available for the frontend build ([Guide 7](../guides/7_frontend.md)). |

---

## Quick reference — deploy (create) in order

Copy `terraform.tfvars.example` → `terraform.tfvars` and edit **before** each `terraform apply` where noted. Paths are from the **repo root** unless stated.

| Step | AWS resources (what you get) | Commands (run in order) | Description |
| --- | --- | --- | --- |
| 1 | **IAM** policies / group for the course user | Follow [`guides/1_permissions.md`](../guides/1_permissions.md) in the **AWS Console** | Grants AWS APIs for later Terraform and runtime services. Not in `terraform/`. |
| 2 | **SageMaker** serverless embedding endpoint + execution role | `cd terraform/2_sagemaker`<br>`cp terraform.tfvars.example terraform.tfvars`<br>`terraform init`<br>`terraform apply` | Embeddings used by ingest Lambda ([`guides/2_sagemaker.md`](../guides/2_sagemaker.md)). Save endpoint name into root `.env` and set `sagemaker_endpoint_name` in **Step 4** `terraform.tfvars` to match (default is often `alex-embedding-endpoint`). |
| 3 | **S3 Vectors** bucket + vector index | **AWS Console** → S3 → **Vector buckets** (see [`guides/3_ingest.md`](../guides/3_ingest.md)) | Separate from normal S3; create **before** research/ingest writes vectors. Bucket name must match what you put in `.env` / later stacks (e.g. `alex-vectors-<account-id>`). |
| 4 | **Ingest** Lambda, **HTTP API Gateway**, usage plan / **API key**, IAM | `cd backend/ingest`<br>`uv run package.py`<br>`cd ../../terraform/3_ingestion`<br>`cp terraform.tfvars.example terraform.tfvars`<br>`terraform init`<br>`terraform apply` | **Depends on:** Step **2** (endpoint name in `terraform.tfvars`). Packages zip, then Terraform deploys ingest + API ([`guides/3_ingest.md`](../guides/3_ingest.md)). Put `ALEX_API_ENDPOINT`, `ALEX_API_KEY`, `VECTOR_BUCKET` into root `.env` for Researcher and local tests. |
| 5a | **ECR** repository, **App Runner** IAM role (partial apply only) | `cd terraform/4_researcher`<br>`cp terraform.tfvars.example terraform.tfvars`<br>`terraform init`<br>`terraform apply -target=aws_ecr_repository.researcher -target=aws_iam_role.app_runner_role` | **Depends on:** Step **4** values in `terraform.tfvars` / `.env` (`alex_api_*`, etc.). Edit **`backend/researcher/server.py`** (Bedrock region + model) per [Guide 4](../guides/4_researcher.md). **Must run before** **5b**. On Windows PowerShell, quote the `-target=...` arguments as in the guide. |
| 5b | **ECR** image (container artifact) | `cd backend/researcher`<br>`uv run deploy.py` | Docker build/push for **linux/amd64** to ECR. On **first** deploy, run **after 5a** and **before 5c** so App Runner can pull an existing image ([`guides/4_researcher.md`](../guides/4_researcher.md)). Later, same command for updates. |
| 5c | **App Runner** service, optional **EventBridge** scheduler | `cd terraform/4_researcher`<br>`terraform apply` | Creates the running Researcher service + optional schedule ([`guides/4_researcher.md`](../guides/4_researcher.md)). |
| 6 | **Aurora Serverless v2**, **Secrets Manager** secret, networking | `cd terraform/5_database`<br>`cp terraform.tfvars.example terraform.tfvars`<br>`terraform init`<br>`terraform apply` | **Does not depend** on Researcher (5a–c). After apply: `terraform output` → copy **cluster** + **secret** ARNs into root `.env` and into `terraform/6_agents/terraform.tfvars` before **8** ([`guides/5_database.md`](../guides/5_database.md)). |
| 7 | **PostgreSQL schema** + seed data (not AWS resources by themselves; uses Data API) | `cd backend/database`<br>`uv run test_data_api.py`<br>`uv run run_migrations.py`<br>`uv run seed_data.py` | **Depends on:** Step **6** and **`AURORA_CLUSTER_ARN` / `AURORA_SECRET_ARN`** in root `.env` ([`guides/5_database.md`](../guides/5_database.md)). |
| 8 | **SQS** queues, **five agent Lambdas** (planner/tagger/reporter/charter/retirement), **S3** lambda-packages bucket, IAM | `cd backend` (repo root)<br>`uv run package_docker.py`<br>`cd ../terraform/6_agents`<br>`cp terraform.tfvars.example terraform.tfvars` (fill Aurora, vectors, Bedrock, Polygon, SageMaker)<br>`terraform init`<br>`terraform apply` | **Depends on:** Steps **2**, **3**, **6**; **strongly** run **7** first so schema/seed exist before agents write. Zips must exist on disk before apply ([`guides/6_agents.md`](../guides/6_agents.md)). After apply: `terraform output sqs_queue_url` → `SQS_QUEUE_URL` in `.env`. |
| 8b (optional) | Same Lambdas (force refresh of code artifacts) | `cd backend`<br>`uv run deploy_all_lambdas.py` | **Only after Step 8.** Optional on first deploy if zips from **8** are already what you want; use after code changes ([`guides/6_agents.md`](../guides/6_agents.md)). |
| 9 | **CloudFront**, **S3** static site bucket, **HTTP API** + **`alex-api` Lambda** | **Recommended:** `cd scripts`<br>`uv sync`<br>`uv run deploy.py`<br><br>**Or manual:** `cd backend/api && uv run package_docker.py` then `cd ../../terraform/7_frontend` + `terraform init/apply`, then `cd ../../frontend && npm install && npm run build` and `aws s3 sync out/ s3://…` + CloudFront invalidation ([`guides/7_frontend.md`](../guides/7_frontend.md)) | **Depends on:** Steps **6** + **8** applied on **this machine** so `terraform/7_frontend` can read `../5_database/terraform.tfstate` and `../6_agents/terraform.tfstate`. `terraform apply` alone does **not** upload the Next.js `out/` site. |
| 10 (optional) | **CloudWatch** dashboards (enterprise stack) | `cd terraform/8_enterprise`<br>`cp terraform.tfvars.example terraform.tfvars`<br>`terraform init`<br>`terraform apply` | Set `bedrock_region` / `bedrock_model_id` to match agent Lambdas ([`guides/8_enterprise.md`](../guides/8_enterprise.md)). |

**Order note (same dependencies, different sequencing):** After Step **4**, you may run **6 → 7** *before* **5a–c**. Researcher only needs ingest (**4**); it does **not** need Aurora.

---

## Quick reference — cleanup (destroy) in order

Default order: remove **user-facing / dependent** stacks first, then **database**, then **research** (so nothing still calls ingest), then **ingest** before **SageMaker** (ingest invokes the endpoint). Confirm with `yes` when Terraform prompts.

**Cost shortcut:** `cd terraform/5_database && terraform destroy` removes the largest steady cost; expect API and agents to fail until Part **5** (and usually **6–7**) are recreated. For a full teardown in one session, prefer **2 → 3 → 4** then continue down the table.

| Step | AWS resources removed | Commands | Description |
| --- | --- | --- | --- |
| 1 | **CloudWatch** dashboards / enterprise extras | `cd terraform/8_enterprise`<br>`terraform destroy` | Drops Guide 8 resources ([`guides/8_enterprise.md`](../guides/8_enterprise.md)). |
| 2 | **CloudFront**, **S3** frontend bucket objects + bucket policy, **API Gateway**, **`alex-api` Lambda**, related IAM | `cd terraform/7_frontend`<br>`terraform destroy`<br><br>**Or** helper (Part 7 only): `cd scripts`<br>`uv run destroy.py` | Destroy **7** while **5** and **6** state still exist if you need Terraform to read remote outputs. `destroy.py` empties the frontend bucket then runs `terraform destroy`. |
| 3 | **SQS** job queue + DLQ, **five agent Lambdas**, **S3** lambda-packages bucket, agent IAM | `cd terraform/6_agents`<br>`terraform destroy` | Removes orchestration stack ([`guides/6_agents.md`](../guides/6_agents.md)). |
| 4 | **Aurora** cluster + **Secrets Manager** DB secret, subnets/SG as defined | `cd terraform/5_database`<br>`terraform destroy` | **Largest ongoing saver** while not developing ([`guides/5_database.md`](../guides/5_database.md)). |
| 5 | **App Runner**, **ECR** repo, scheduler Lambda + **EventBridge** (if created) | `cd terraform/4_researcher`<br>`terraform destroy` | Stops Researcher / scheduler cost ([`guides/4_researcher.md`](../guides/4_researcher.md)). **Before** Step **6** so the service is not left pointing at an ingest API you are about to delete. |
| 6 | **Ingest** Lambda, ingest **API Gateway**, API key resources, IAM | `cd terraform/3_ingestion`<br>`terraform destroy` | Removes ingest HTTP API ([`guides/3_ingest.md`](../guides/3_ingest.md)). **Before** Step **7** (SageMaker) because ingest invokes the embedding endpoint. |
| 7 | **SageMaker** endpoint + model + roles | `cd terraform/2_sagemaker`<br>`terraform destroy` | Removes embedding endpoint ([`guides/2_sagemaker.md`](../guides/2_sagemaker.md)). |
| 8 | **S3 Vectors** bucket + indexes | **AWS Console** → Vector buckets → delete | **Not** deleted by `terraform/3_ingestion` destroy; must be removed manually ([`guides/3_ingest.md`](../guides/3_ingest.md)). |
| 9 | **IAM** group/policies from Guide 1 | **AWS Console** (optional) | Optional cleanup of course IAM ([`guides/1_permissions.md`](../guides/1_permissions.md)). |

---

## Figure A — How services fit together (architecture roles)

Use this mental model when deciding **create order** and **destroy order**. (Compare to the “enterprise / multi-agent” diagram in the course materials.)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ USER                                                                        │
│  Browser ──HTTPS──► CloudFront ──► S3 (static Next.js export)               │
│           └──auth──► Clerk (SaaS, not AWS)                                  │
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
 ┌──────────────┐                      │                              │
 │ Planner      │──invoke──────────────┼──► Tagger / Reporter /       │
 │ (Lambda)     │   (async)            │     Charter / Retirement     │
 └──────┬───────┘                      │     (Lambdas + Bedrock)      │
        │                              │                              │
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
| Research → ingest → vectors narrative | [`docs/2_data-pipeline.md`](2_data-pipeline.md) |
| Broader architecture / costs | [`docs/3_architecture.md`](3_architecture.md) |
| Multi-agent collaboration diagram | [`docs/4_agent_architecture.md`](4_agent_architecture.md) |
| Course steps | [`guides/`](../guides/) |
