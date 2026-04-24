## `terraform/4_researcher` — Researcher on App Runner (+ optional scheduler)

This stack provisions:
- an **ECR repo** for the Researcher container image
- an **App Runner service** (`alex-researcher`) that runs the container
- optional **EventBridge Scheduler → Lambda** automation to call the service on a schedule (Guide 4).

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| ECR | `alex-researcher` repo | Stores the Researcher container image. |
| IAM | `alex-app-runner-role` | Lets App Runner pull from private ECR. |
| IAM | `alex-app-runner-instance-role` + Bedrock policy | Runtime role for the container (Bedrock access). |
| App Runner | `alex-researcher` service | Runs the Researcher API (port 8000). |
| (Optional) EventBridge Scheduler | scheduler role + schedule | Triggers research periodically (if enabled). |
| (Optional) Lambda | `alex-researcher-scheduler` + role/policies | Calls the App Runner `/research` endpoint. |

---

## Prerequisites / dependencies

| Dependency | Why |
| --- | --- |
| `terraform/3_ingestion` applied | App Runner env includes `ALEX_API_ENDPOINT` and `ALEX_API_KEY` for ingest calls. |
| `OPENAI_API_KEY` available | Passed into the container as an env var (tracing / SDK usage in the Researcher). |
| Docker image push step | Terraform creates the ECR repo and App Runner wiring; the actual image is built/pushed by `backend/researcher/deploy.py`. |

---

## Key inputs

| Variable | Meaning |
| --- | --- |
| `openai_api_key` | Passed into the container. |
| `alex_api_endpoint` / `alex_api_key` | Ingest API details used by the Researcher service. |
| `scheduler_enabled` | If true, creates scheduler resources (Lambda + EventBridge). |

---

## Outputs you’ll use

| Output | Why |
| --- | --- |
| `ecr_repository_url` | Used by the image push step (`backend/researcher/deploy.py`). |
| `app_runner_service_url` / `app_runner_service_id` | Testing + operational management (pause/resume/metrics). |

---

## ASCII flow

```
Docker build/push (local)  --->  ECR repo alex-researcher
                                     |
                                     v
                              App Runner service
                              alex-researcher:8000
                                     |
                                     v
                         calls ingest API (API Gateway)

(optional)
EventBridge Scheduler  ->  Lambda alex-researcher-scheduler  ->  App Runner /research
```

---

## How Terraform builds it (in plain terms)

1. Creates the ECR repo.
2. Creates App Runner access role (for ECR pull) and instance role (for runtime AWS access).
3. Creates App Runner service pointing at `${repo_url}:latest` (auto-deploy disabled).
4. If `scheduler_enabled=true`, creates an EventBridge Scheduler role, a scheduler Lambda, and schedule resources that invoke the service.

