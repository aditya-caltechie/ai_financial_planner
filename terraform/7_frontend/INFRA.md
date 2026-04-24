## `terraform/7_frontend` — CloudFront + static frontend + API Gateway + API Lambda

This stack provisions the user-facing layer (Guide 7):
- an S3 bucket configured for static website hosting
- a CloudFront distribution in front of that bucket
- an API Gateway HTTP API + Lambda integration (`alex-api`)
- IAM for the API Lambda to talk to Aurora (Data API) and SQS (job submission).

It also reads **local Terraform remote state** from:
- `../5_database/terraform.tfstate`
- `../6_agents/terraform.tfstate`

so it can wire DB/SQS values into IAM and Lambda env vars.

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| S3 (standard) | `alex-frontend-<account-id>` + website config + policy | Hosts the exported Next.js static site. |
| CloudFront | distribution (comment: “Alex Financial Advisor Frontend”) | CDN in front of S3; also routes `/api/*` to API Gateway. |
| IAM | `alex-api-lambda-role` + policies | Basic logging + (when available) Aurora Data API + SQS send + Lambda invoke. |
| Lambda | `alex-api` | Backend API Lambda packaged locally (`backend/api/api_lambda.zip`). |
| API Gateway v2 (HTTP) | `alex-api-gateway` | Public HTTP entrypoint for the API Lambda. |

---

## Prerequisites / dependencies

| Dependency | Why |
| --- | --- |
| `terraform/5_database` applied on this machine | Remote state provides `aurora_cluster_arn` + `aurora_secret_arn`. |
| `terraform/6_agents` applied on this machine | Remote state provides `sqs_queue_url` / ARN. |
| API zip built locally | `backend/api/api_lambda.zip` must exist before `terraform apply`. In practice `scripts/deploy.py` builds this. |
| Frontend build/upload | Terraform does not upload `frontend/out/`; `scripts/deploy.py` performs build + `aws s3 sync` + CloudFront invalidation. |

---

## Notes on destroy resilience

This stack is written to be **destroy-friendly** even if `5_database` and/or `6_agents` were already destroyed:
- Remote outputs are accessed via `try(..., null)`.
- DB/SQS IAM policies are conditional (`count = ... ? 1 : 0`).

For a correct **apply** in the guide flow, still run **Part 5 → Part 6 → Part 7** so the remote outputs exist.

---

## ASCII flow

```
Browser
  |
  v
CloudFront  ---->  S3 static site (frontend)
   |
   | /api/*
   v
API Gateway (HTTP)  ->  Lambda alex-api
                           | \
                           |  \-> SQS SendMessage (jobs)
                           |
                           \-> Aurora Data API (cluster ARN + secret)
```

---

## How Terraform builds it (in plain terms)

1. Creates an S3 bucket and enables website hosting + public read policy.
2. Creates an IAM role/policies for the API Lambda.
3. Creates the `alex-api` Lambda (zip file path is local).
4. Creates an API Gateway HTTP API with Lambda integration.
5. Creates CloudFront with:
   - S3 origin for static assets
   - API origin for `/api/*` routes

