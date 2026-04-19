# Alex Multi‑Agent Architecture (Guide + Code Truth)

This doc merges:
- **Intent / explanation** from `guides/agent_architecture.md`
- **Reality / implementation** from the actual code in `backend/*` and Terraform in `terraform/5_database` + `terraform/6_agents`

It focuses on what matters most to build these agents on AWS: **event shapes, state boundaries (“memory”), tool/structured output/MCP usage, and how Lambdas + SQS + Aurora + S3 Vectors fit together**.

---

## Collaboration Overview (ASCII)

```
                         (autonomous knowledge building)
EventBridge schedule ──► App Runner: Researcher (FastAPI)
                            |    \
                            |     \── MCP: Playwright browser
                            |
                            \── tool: ingest_financial_document(topic, analysis)
                                     |
                                     v
                              API Gateway ingest (x-api-key)
                                     |
                                     v
                          Ingest Lambda -> SageMaker embed -> S3 Vectors


                        (user-triggered portfolio analysis)
User/API/Frontend -> create `jobs` row -> SQS: alex-analysis-jobs (job_id)
                                     |
                                     v
                                Lambda: Planner
                            (pre-steps + tool orchestration)
                            /      |           \
                           /       |            \
               Lambda: Tagger   Lambda: Reporter  Lambda: Charter  Lambda: Retirement
            (structured output)   (tools+RAG)       (JSON output)     (simulation+LLM)
                   |                 |                 |                 |
                   v                 v                 v                 v
              Aurora: instruments  Aurora: jobs.report  Aurora: jobs.charts  Aurora: jobs.retirement

Reporter tool: get_market_insights
  -> SageMaker embeddings + S3 Vectors query
```

---

## Key Design Principles (from the guide, validated against code)

- **Specialization**: each agent does one job well (Tagger, Reporter, Charter, Retirement).
- **Orchestration**: Planner coordinates and delegates.
- **Externalized memory**: “memory” is not chat history; it lives in **Aurora** and **S3 Vectors**.
- **Reliability via constraints**:
  - Tagger uses **structured outputs** (schema + validators).
  - Charter forces “JSON-only” output then parses/normalizes before DB write.
  - Reporter can “judge” its output and fail safe if quality is too low.

---

## What “Agent Features” Are Used Where

### Tool calling
- **Planner**: tools that invoke other Lambdas (`invoke_reporter`, `invoke_charter`, `invoke_retirement`)
- **Reporter**: tool for retrieval (`get_market_insights`)
- **Researcher**: tool to persist research (`ingest_financial_document`)

### Structured outputs
- **Tagger only**: `output_type=InstrumentClassification` + `final_output_as(...)`

### MCP servers
- **Researcher only**: Playwright MCP for browser automation

### “Memory”
- **Aurora DB**: portfolios + job outputs (JSONB columns)
- **S3 Vectors**: research snippets (long-lived knowledge base)

---

## AWS Infrastructure Wiring (Terraform Truth)

### Database (Part 5)
From `terraform/5_database`:
- **Aurora Serverless v2 Postgres** with **Data API enabled**
- Credentials in **Secrets Manager**
- This is what enables Lambdas to read/write without VPC connection pooling

### Agent Orchestra (Part 6)
From `terraform/6_agents`:
- **SQS** queue `alex-analysis-jobs` + DLQ
- **Lambdas**:
  - `alex-planner` (SQS triggered, 900s timeout, 2048MB)
  - `alex-tagger`, `alex-reporter`, `alex-charter`, `alex-retirement` (300s timeout, 1024MB)
- **IAM** allows:
  - `rds-data:*` + `secretsmanager:GetSecretValue`
  - `lambda:InvokeFunction` (`alex-*`) for Planner delegation
  - `sagemaker:InvokeEndpoint` + `s3vectors:QueryVectors/GetVectors` for Reporter retrieval
  - `bedrock:InvokeModel*` for all agents via LiteLLM

---

## Communication Flow (Guide intent, with code-level precision)

### 1) Independent Research Flow (every 2 hours)

```
EventBridge -> Researcher (App Runner)
  -> MCP: browse sites
  -> tool: ingest_financial_document
     -> API Gateway ingest -> Ingest Lambda -> SageMaker -> S3 Vectors
```

### 2) User-triggered Analysis Flow

```
User request -> job created in Aurora -> SQS message (job_id)
SQS -> Planner Lambda
  -> (pre-step) Tagger Lambda if missing instrument allocations
  -> (pre-step) Polygon price updates into Aurora instruments.current_price
  -> Planner agent uses tools to invoke Reporter/Charter/Retirement
  -> Each agent writes to its own jobs.*_payload JSONB column
  -> Planner marks job completed (or failed)
```

---

## Agent Responsibilities (Guide + Reality)

### Planner (Financial Planner / Orchestrator) — `backend/planner`
- **Trigger**: SQS event (`Records[0].body` is job_id)
- **Pre-processing (non-LLM)**:
  - detect missing allocations and invoke Tagger
  - update prices via Polygon into `instruments.current_price`
- **Agent behavior**: an LLM with **3 tools** that invoke other Lambdas
- **Writes**: job `status` (and failure `error_message`)

### Tagger (InstrumentTagger) — `backend/tagger`
- **Input**: `{"instruments":[{"symbol","name"},...]}`
- **Agent feature**: **structured outputs** (Pydantic schema + validators)
- **Writes**: upserts `instruments.*allocation_*` JSONB and basic metadata

### Reporter (Report Writer) — `backend/reporter`
- **Input**: usually `{"job_id": ...}` (loads portfolio/user from Aurora if missing)
- **Agent feature**: tool calling for retrieval (`get_market_insights`)
- **Retrieval path**: SageMaker embed -> S3 Vectors query -> short snippets
- **Writes**: `jobs.report_payload = {"content": "...markdown...", ...}`
- **Extra reliability**: “judge” step; if score too low, emits a safe fallback

### Charter (Chart Maker) — `backend/charter`
- **Input**: usually `{"job_id": ...}` (loads portfolio from Aurora if missing)
- **Agent feature**: “JSON-only” constrained output (then parsed/normalized)
- **Writes**: `jobs.charts_payload` (dict keyed by chart key)

### Retirement (Retirement Specialist) — `backend/retirement`
- **Input**: usually `{"job_id": ...}` (loads portfolio from Aurora if missing)
- **Deterministic core**: Monte Carlo simulation + projections are computed before LLM
- **Writes**: `jobs.retirement_payload = {"analysis": "...markdown...", ...}`

### Researcher (Independent Agent) — `backend/researcher`
- **Runs on**: FastAPI service (App Runner), not part of Part 6 Lambdas
- **Agent features**: **MCP Playwright** + tool (`ingest_financial_document`)
- **Writes**: S3 Vectors (indirectly via the ingest pipeline)

---

## Capability Matrix (updated to match code)

| Agent | Runtime | Trigger | “Agent feature” emphasis | Reads | Writes |
|------|---------|---------|---------------------------|-------|--------|
| Planner | Lambda | SQS | Tools (invoke other Lambdas) | Aurora | jobs.status |
| Tagger | Lambda | Lambda invoke | Structured outputs | Aurora | instruments |
| Reporter | Lambda | Lambda invoke | Tools (RAG via S3 Vectors) | Aurora, SageMaker, S3 Vectors | jobs.report_payload |
| Charter | Lambda | Lambda invoke | Constrained JSON output + parsing | Aurora | jobs.charts_payload |
| Retirement | Lambda | Lambda invoke | Deterministic sim + LLM narrative | Aurora | jobs.retirement_payload |
| Researcher | App Runner | EventBridge / HTTP | MCP + tool | Web, (optional) | S3 Vectors (via ingest) |

---

## Where the Guide Differs from Current Code (important)

- **Guide says** Planner “retrieves context from S3 Vectors.”  
  **Current implementation**: retrieval from S3 Vectors is implemented in **Reporter’s** tool `get_market_insights`. Planner itself does not query vectors.

- **Guide shows** parallel agent execution.  
  **Current implementation**: Planner tool calls are made from an LLM run; the tool invocations are effectively sequential unless you explicitly build parallelism into the orchestrator/tool layer.

These are not problems—just important to understand when you extend the system.

