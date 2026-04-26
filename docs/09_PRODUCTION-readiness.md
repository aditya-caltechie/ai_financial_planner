# Production-ready (Enterprise checklist)

This is a concise, “what to focus on” companion to **Guide 8**. For the full, step-by-step implementation (Terraform, commands, and code pointers), refer to `guides/8_enterprise.md`.

## Big-picture flow (end-to-end)

```text
Browser
  |
  v
CloudFront -> S3 (Next.js static)
  |
  v
API Gateway -> API Lambda (FastAPI) -> Aurora (Data API)
                     |
                     v
                   SQS queue  ---> DLQ (failed jobs)
                     |
                     v
             Planner (orchestrator) Lambda
               |      |       |         |
               v      v       v         v
            Tagger  Reporter Charter  Retirement   (specialist Lambdas)
               \       |       |         /
                \      v       v        /
                 ---> Aurora (results, state)
                       |
                       v
                Frontend reads results

Optional background knowledge plane:
EventBridge schedule -> Scheduler Lambda -> Researcher (App Runner) -> API Gateway -> Ingest Lambda
                                                     |                               |
                                                     v                               v
                                                   Bedrock                        SageMaker embeddings
                                                                                      |
                                                                                      v
                                                                                  S3 Vectors (retrieval)
```

## What “enterprise-grade” means here

- **Scalable**: predictable performance under load, protected from abuse, and cost-aware scaling.
- **Secure**: least privilege, strong authn/authz, safe data handling, and layered perimeter controls.
- **Observable**: dashboards + alerts + traces to debug failures and manage cost/latency.
- **Guarded**: validation and safe fallbacks so AI mistakes don’t become user-visible incidents.
- **Operable**: deployable, testable, and recoverable with clear runbooks.

## 1) Scalability (capacity + cost + safety)

### Must focus on

- **Lambda concurrency strategy**
  - Use **reserved concurrency** for critical Lambdas (planner/API) to guarantee capacity.
  - Use **timeouts** and **memory sizing** intentionally (latency vs cost).
  - Avoid “thundering herd”: planner should control fan-out and cap parallel invocations.
- **Aurora Serverless v2 scaling**
  - Increase `max_capacity` when needed; keep `min_capacity` cost-efficient.
  - Treat DB as the shared bottleneck: measure query latency and connection pressure (Data API).
- **API Gateway throttling**
  - Set per-route and/or stage throttles to protect Lambda and costs.
  - Add request size limits and conservative defaults for public endpoints.
- **SQS buffering**
  - SQS decouples UI/API from long-running agent work; tune visibility timeouts and retries.

### Common scaling additions (often needed in real production)

- **Backpressure & prioritization**
  - Separate queues (e.g., “interactive” vs “batch research”) or add message attributes for priority.
- **Idempotency**
  - Ensure SQS jobs are safe to reprocess (dedupe keys, “job already completed” checks).
- **Load testing**
  - Run controlled load against API routes and measure: p95 latency, error rate, throttles, DB load.

## 2) Security (layered defense)

### Must focus on (baseline)

- **Authn/authz**
  - Clerk **JWT verification** on every API request.
  - Enforce **per-user isolation** (all DB reads/writes filtered by `clerk_user_id`).
- **IAM least privilege**
  - Each Lambda role: only the actions/resources it truly needs (RDS Data API, invoke specific Lambdas, SQS, logs).
- **Secrets management**
  - Use **Secrets Manager** (no credentials in code), encrypted at rest (KMS).
- **API perimeter controls**
  - API Gateway throttling + strict **CORS** + security headers (CSP) to reduce browser abuse surface.

### Enterprise add-ons worth considering (defense-in-depth)

- **AWS WAF** in front of API Gateway/CloudFront
  - Managed rules (SQLi/XSS/bots) + rate limiting.
  - Cost trade-off: pay per request + rules; use where threat model justifies it.
- **Private connectivity**
  - VPC endpoints where appropriate (S3, Secrets Manager, etc.) to reduce public egress exposure.
- **Threat detection**
  - **GuardDuty** + CloudTrail monitoring for unusual access patterns.

### Security gaps to explicitly decide (don’t skip the decision)

- **Data classification & privacy**
  - What is “PII” in your app? How is it stored, retained, and deleted?
- **Encryption in transit**
  - TLS is standard at the edge; confirm any internal calls (e.g., to services) also use TLS.
- **Secrets rotation**
  - Decide rotation cadence and blast radius (DB creds, API keys, third-party tokens).

## 3) Monitoring (CloudWatch + alarms + dashboards)

### Must focus on

- **Structured logging**
  - Emit consistent JSON logs for: request start/end, job creation, planner start/end, agent invoke, agent success/fail.
  - Include: `job_id`, `clerk_user_id`, `agent_name`, `duration_ms`, `status`, and error summaries.
- **Dashboards**
  - Track: API 4xx/5xx, Lambda errors/throttles/duration, SQS backlog/age, Aurora capacity and latency.
- **Alerts**
  - Alarms on: sustained Lambda errors, timeouts, throttles, SQS age/backlog, DLQ messages > 0.
  - Route alerts via SNS (email is fine for a course project; paging tools for real prod).
- **Cost monitoring**
  - Set budgets/alerts and review costs after changes that affect throughput (agents, researcher schedule).

### Operational reliability additions

- **Dead Letter Queues (DLQ) + redrive**
  - Ensure each critical queue has a DLQ; define a redrive strategy and “how to replay safely”.
- **Runbooks**
  - A 1–2 page “what to do when X breaks” doc beats guesswork during incidents.

## 4) Guardrails (reduce AI failure modes)

### Must focus on

- **Output validation**
  - Validate agent outputs before saving/serving. Example: Charter JSON schema checks and safe fallback.
- **Input validation + prompt-injection hygiene**
  - Sanitize and validate user-controlled text and symbols.
  - Prefer allow-lists (e.g., ticker format regex) over block-lists when possible.
- **Size and budget limits**
  - Cap response size, max tool usage, and max turns (protect latency and cost).
- **Retries with exponential backoff**
  - Use tenacity-style retries for transient model/service failures; avoid infinite retry loops.

### Guardrails that help in regulated/enterprise settings

- **Policy checks before recommendations**
  - If your app makes “advice-like” statements: add disclaimers, constraint checks, and confidence thresholds.
- **Human-readable error states**
  - Fail safely with a clear user message and a logged diagnostic trail.

## 5) Explainability (trust + compliance)

### Must focus on

- **Rationale captured at decision time**
  - Add a `rationale` field to structured outputs (e.g., Tagger) and log it.
  - Put rationale *before* the final classification in the schema so the model reasons first.
- **Audit trail**
  - Record what ran: agent name, model id, inputs/outputs (or hashes), and timings.
  - Decide retention and access controls for audit logs.

## 6) Observability (LangFuse tracing)

### Must focus on

- **End-to-end tracing**
  - Instrument each Lambda handler with a context manager so traces flush on exit (critical on Lambda).
- **Token usage + cost visibility**
  - Track token usage per agent/job so you can manage spend and find hotspots.
- **Troubleshooting workflow**
  - If a user reports a “bad analysis”, you should be able to find the job trace by `job_id` and see prompts, responses, and failure points.

## 7) Production hygiene (often missed, but important)

- **CI/CD**
  - Automated checks: lint/test, build/package, terraform plan, deploy with approvals for prod.
- **Environment separation**
  - Distinct dev/stage/prod stacks, isolated data, and different rate limits + alerting thresholds.
- **Backups / recovery**
  - Confirm Aurora backup settings and practice restore (even once).
- **SLOs and budgets**
  - Pick simple targets (p95 latency, error rate, max queue age) and alert on violations.
- **Change management**
  - Canary or phased rollouts for risky changes; keep a rollback plan.

## Practical “do this first” checklist

- **Scale**: set API Gateway throttles; set reserved concurrency for API + planner; confirm SQS visibility + DLQ.
- **Security**: verify Clerk JWT validation on all endpoints; least-privilege IAM; Secrets Manager in use; CORS/CSP sane.
- **Monitoring**: structured JSON logs; CloudWatch dashboards; alarms to SNS; DLQ alarms.
- **Guardrails**: validate charter JSON output; validate inputs; response size limits; retries/backoff.
- **Explainability**: add rationales + audit logs for key decisions.
- **Tracing**: LangFuse working end-to-end; you can find a single job and replay what happened.

## References

- Primary, detailed guide: `guides/8_enterprise.md`
- Helpful related docs (optional): `docs/8_cloudwatch-logs.md`, `docs/7_aws-deployment.md`, `docs/6_database-lifecycle.md`

