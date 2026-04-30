# Alex — Agentic Learning Equities eXplainer

[![CI](https://github.com/aditya-caltechie/ai_financial_planner/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aditya-caltechie/ai_financial_planner/actions/workflows/ci.yml)

**Alex** is a production-style, multi-agent financial planning platform. It combines portfolio intelligence, AI-assisted market research, embeddings-backed retrieval, and a Next.js frontend with Clerk authentication.

This repository is the capstone project for the “AI in Production” course and is designed to be deployed on AWS using Terraform.

## What’s included

- **Multi-agent system** (Planner + specialist agents) running on **AWS Lambda**
- **Researcher service** running on **AWS App Runner** (optionally scheduled)
- **Knowledge pipeline**: ingestion → embeddings → **S3 Vectors**
- **Backend API**: FastAPI on Lambda (used by the frontend)
- **Frontend**: Next.js (Pages Router) + Clerk
- **Infrastructure as Code**: independent Terraform stacks (`terraform/2_sagemaker` … `terraform/8_enterprise`)

## Tech stack

| Area | Technologies |
| --- | --- |
| **Cloud** | AWS Lambda, App Runner, API Gateway, S3 / S3 Vectors, SageMaker (serverless inference), Bedrock, EventBridge Scheduler, ECR, Aurora Serverless v2 (later stacks), SQS, CloudFront, etc. |
| **IaC** | Terraform (independent state per `terraform/*` directory) |
| **Agents / API** | Python 3.12+, **uv**, FastAPI (`backend/api`), **OpenAI Agents SDK** + LiteLLM → Bedrock |
| **Frontend** | Next.js (Pages Router), React, TypeScript, Tailwind, **Clerk** |
| **Containers** | Docker (Researcher image build/push) |
| **Course tooling** | AWS CLI, `uv run` for all Python entrypoints |

## Repository layout

| Path | Role |
| --- | --- |
| **[backend/](backend/)** | Agents, API, ingest, database library—**each subfolder is a uv project** |
| **[frontend/](frontend/)** | Next.js app; needs `frontend/.env.local` (Clerk) |
| **[terraform/](terraform/)** | One independent stack per directory (`2_sagemaker` … `8_enterprise`) |
| **[scripts/](scripts/)** | Local dev (`run_local.py`) and frontend/API helpers (`deploy.py`, `destroy.py`) |
| **[aws/](aws/)** | **Full-stack** AWS orchestration: `deploy_all_aws.py`, `destroy_all_aws.py`, validate scripts — see **[aws/README.md](aws/README.md)** |

**Recommended order:** `terraform/2_sagemaker` → `terraform/3_ingestion` → `terraform/4_researcher` → `terraform/5_database` → `terraform/6_agents` → `terraform/7_frontend` → `terraform/8_enterprise`. For each stack directory, copy `terraform.tfvars.example` to `terraform.tfvars` before running `terraform apply`.

## Getting started

### Prerequisites

- **uv** ([install](https://docs.astral.sh/uv/)) — run Python with `uv` (don’t use `pip` directly).
- **Node.js** and **npm** — for the frontend.
- **AWS account + AWS CLI** configured (for deployed stacks and any tests that call AWS).
- **Docker Desktop** — when packaging Lambdas with Docker or building the Researcher image.

### Full local app (API + Next.js)

Used once you have the **FastAPI** backend and **frontend** configured (root `.env` + Clerk keys).

1. From the repo root, create **`/.env`** (you can start from `.env.example`).
2. Create **`frontend/.env.local`** with your **Clerk** publishable key and related vars.
3. Start both services:

```bash
cd scripts
uv sync
uv run run_local.py
```

- Frontend: **http://localhost:3000**  
- Backend: **http://localhost:8000** (OpenAPI: **http://localhost:8000/docs**)  
- Stop with **Ctrl+C**.

### Research / ingest only (without full UI)

Deploy the relevant Terraform stacks (typically `2_sagemaker`, `3_ingestion`, `4_researcher`), then run the local tests, for example:

```bash
cd backend/ingest && uv run test_ingest_s3vectors.py
cd backend/researcher && uv run test_research.py
```

Always use **`uv run …`** inside the relevant `backend/<package>` directory.

## Deploying on AWS

### Step-by-step (Terraform)

Each `terraform/<stack>/` directory is independent. Configure `terraform.tfvars` in that directory, then run Terraform in stack order. See `terraform/README.md` for details.

### One-command orchestration (`aws/`)

After you have **AWS CLI**, **Terraform**, **Docker**, **uv**, **npm**, and the per-stack config files in place (`terraform/*/terraform.tfvars`, root **`.env`**, Clerk vars for the frontend), you can drive the **full stack** from the **`aws/`** uv project.

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

See **[aws/README.md](aws/README.md)** for flags like `--dry-run`, partial runs, and stack ordering/caveats.

## Documentation

- **AWS orchestration:** `aws/README.md`
- **Terraform stacks:** `terraform/README.md`
- **Project notes:** `AGENTS.md` and `CLAUDE.md`

## Notes and troubleshooting

- **Docker is required** for packaging some Lambda artifacts and for building/pushing the Researcher container image.
- **S3 Vectors cleanup**: vector buckets/indexes may not be deleted by automated destroy flows; remove them in the AWS console if you want all vector-related costs gone.

