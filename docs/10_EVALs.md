# Evaluations (RAG, Agents, Models, Systems) — Taxonomy + Metrics + Examples

This note is a **clean mental model** for evaluating LLM systems in production. It maps naturally to Alex-style architectures where you have:

- **Retrieval** (S3 Vectors / embeddings / “what context did we fetch?”)
- **Agents** (tool calls, multi-step workflows, orchestration)
- **Safety** (prompt injection, PII, toxicity)
- **Model capability** (baseline LLM quality before/after changes)
- **Production systems** (latency, throughput, cost, reliability)

---

## Evaluation taxonomy (component → full autonomous system)

This is the “big picture” classification: you usually evaluate **multiple layers** because failures can originate in retrieval, tool use, the underlying model, production infrastructure, or policy/guardrails.

Each major category below follows the same **outline** (names differ by domain):

| Block | What it usually contains |
|--------|--------------------------|
| **Layer metrics** | Quantitative signals *native to that component* (RAG splits into **retrieval** vs **generation**; agents split into **trajectory** vs **outcome**). |
| **Rubrics & suites** | Judge scores, adversarial prompt suites, or fixed benchmark sets—where pass/fail is partly qualitative. |
| **How to measure** | Where labels come from (gold data, judges, logs) and what belongs in **CI** vs **offline** vs **production** monitoring. |

**Same story, three stops** (every section below follows this left-to-right habit):

```text
  Layer metrics          Rubrics / suites           How to measure
       |                        |                        |
       v                        v                        v
  (numbers from          (judges, attacks,        (gold labels,
   the component)         benchmark sets)          CI vs prod logs)
```

**Where failures hide** (evaluate the layer that actually broke):

```text
        +-------------------------+
        |   Safety / policy       |  prompt injection, PII, refusals
        +------------+------------+
                     |
        +------------v------------+
        |  Agent (tools, state)   |  trajectory + outcome metrics
        +------------+------------+
                     |
        +------------v------------+
        |  RAG (retrieve + answer)|  retrieval vs generation metrics
        +------------+------------+
                     |
        +------------v------------+
        |  Foundation model       |  benchmarks, formatting regressions
        +------------+------------+
                     |
        +------------v------------+
        |  Ops (latency, cost)    |  SLOs, queues, error budgets
        +-------------------------+
```

---

### RAG evals (retrieval + grounding)

RAG evals focus on the **knowledge layer**: did we find the right evidence, and did the model stay anchored to it?

```text
  [ User question ]
         |
         v
   +-----------+   top-k    +------------------+
   | Retriever | --------> | chunks / passages |
   +-----------+            +--------+---------+
         |                            |
  1) Retrieval metrics                | read as context
  (recall, MRR, nDCG, ...)            v
                               +-------------+
                               | LLM + prompt|
                               +------+------+
                                      |
                                      v
                               +-------------+
                               |   Answer    |
                               +-------------+
                                      |
                    +--------------------+--------------------+
                    | 2) Generation      | 3) End-to-end      |
                    | (faithfulness,     | rubrics (judge)    |
                    |  relevance)        |                    |
                    +--------------------+--------------------+
```

#### 1) Retrieval metrics (the search)

- **Context recall**: did retrieval surface *enough* of the relevant evidence to answer the question?
- **Context precision**: of what was retrieved, how much was actually relevant? (noise contributes to “lost in the middle” failures)
- **MRR (mean reciprocal rank)**: where does the *first* relevant item appear in the ranked list? (“best hit” ranking quality.)
- **nDCG (normalized discounted cumulative gain)**: rewards putting *multiple* relevant items high in the list, with diminishing credit deeper in the ranking—useful when users skim top‑k chunks or several passages should be retrieved together.
- **MAP / precision@k / recall@k** (optional): common when you fix a cutoff *k* (e.g., top 5 chunks) and care about density of good hits in that window.

**MRR vs nDCG (when to use which):** use **MRR** if “any one gold passage near the top is enough”; use **nDCG** when **order and breadth** of relevant passages matter (multi-evidence questions, long contexts, reranking comparisons).

**Optional — lexical / hybrid signals (dataset-dependent):**

- **Keyword coverage** (or similar): overlap between query/gold terms and retrieved text (or between gold answer and generation). Cheap for keyword-heavy corpora; weak alone under paraphrase unless paired with semantic retrieval.

#### 2) Generation metrics (the answer, given retrieved context)

- **Faithfulness / groundedness**: is every substantive claim supported by retrieved context? (Primary anti-hallucination check.)
- **Answer relevance**: does the answer address the user’s question (even if retrieval was imperfect)?

#### 3) End-to-end rubrics (often human or LLM-as-judge)

Often reported as 1–5 scores **alongside** retrieval metrics—not a substitute for faithfulness unless definitions align.

- **Accuracy** (name varies): factual correctness vs a **reference answer** or expert judgment—not the same as faithfulness unless the rubric ties claims to retrieved context.
- **Completeness**: whether required sub-facts or checklist items are covered.
- **Relevance**: alignment with user intent (overlaps with “answer relevance,” but is not the same as faithfulness to retrieved context).

#### 4) How to measure (RAG)

- **Retrieval labels**: human relevance grades, gold chunk IDs, or structured ground truth for automated overlap checks.
- **Faithfulness / answer quality**: LLM-as-judge with a strict rubric, or libraries that ship judge prompts + scores (e.g., Ragas-style workflows).
- **Runs to compare**: separate **retrieval-only** evals from **end-to-end** (retrieve + generate) when debugging regressions.

**Why retrieval can improve while “accuracy” drops:** reranking / richer context can surface **conflicting** passages, add **noise** that hurts the reader model, or change **what the judge rewards** (e.g., stricter citation expectations). Treat that as a signal to add **faithfulness** and explicit rubric notes—not only ranking metrics.

---

### Agentic evals (reasoning + action)

Agentic systems are **loops**: planning, tool use, recovery, and side effects. Use the same mental split as RAG—**path** (what it did) vs **result** (what changed)—plus rubrics for how it *felt* to the user.

```text
                    +------------------+
         +--------->| Tools / APIs / UI|
         |          +---------+--------+
         |                |
         |                v
  +------+------+   +--------------+    observe    +-------------+
  | Agent brain |   | Environment  |-------------->| State / DB  |
  +------+------+   +--------------+               +-------------+
         ^                ^
         |                |
         +----------------+   (loop until stop / success / budget)

  Score PATH:  tool choice, order, args, retries, step count
  Score WORLD: job status, rows written, files, final payload schema
  Score UX:     helpfulness, policy (often judge-based)
```

#### 1) Trajectory & control metrics (the path)

*Which tools, when, with what arguments, and how efficiently.*

- **Tool selection accuracy**: correct tool for the intent (e.g., weather vs calculator).
- **Argument correctness**: parameters match intent + valid schema (exact match, fuzzy match for free text, or validator pass/fail).
- **Trajectory shape** (compare when you change planner, prompts, or tool set—like ranking metrics for ordered actions):
  - **Strict sequence match**: full predicted chain equals gold (brittle if many valid orderings exist).
  - **Set overlap / precision–recall on tools**: right *set* of tools regardless of order.
  - **Prefix / “first error”**: how many initial steps were correct before the first mistake.
  - **Recovery quality**: after a tool error, sensible backtrack/retry vs loops.
- **Step efficiency**: solved in ~N steps vs thrashing (cost + reliability).
- **Reasoning trace quality** (if logged): plan progresses logically vs repeating dead ends.

#### 2) Outcome & state metrics (the world after the run)

*What actually changed—what production cares about.*

- **Success rate**: runs that reach a correct terminal state (binary or graded).
- **Reliability / consistency**: same task across trials—stable success vs stochastic failure.
- **State assertions**: DB rows, job status transitions, files, API effects; payload schema checks (e.g., chart JSON).

#### 3) End-to-end rubrics (human or LLM-as-judge)

- **Helpfulness / clarity** of the final user-facing message (artifact can be “correct” but unusable).
- **Policy adherence**: avoided disallowed actions (e.g., write tool without confirmation) even when output looks fine.

#### 4) How to measure (agentic)

- **Deterministic / CI-friendly:** golden trajectories (expected tool sequence or acceptable variants), JSON Schema on arguments, idempotency keys, DB snapshots, workflow state machines.
- **Judge-based:** LLM grades plan quality, explanations, or style—**version** rubrics and spot-check against humans.
- **Trajectory vs outcome:** use **trajectory** scores to debug orchestration quickly; use **outcome + state** for release gates. They can diverge—e.g., higher tool accuracy but worse user scores from redundant calls, suboptimal paths, noisy intermediate errors, or a valid trajectory your strict gold trace penalizes.

---

### Foundation / LLM evals (the “brain”)

Capability of the **base model** in isolation or under controlled prompts—before blaming RAG or agents.

#### 1) Capability metrics

- **Knowledge breadth**: multitask knowledge suites (e.g., MMLU-style families).
- **Reasoning & code**: math word problems, coding exercises (e.g., GSM8K-style / HumanEval-style families).

#### 2) How to measure (foundation)

- **Benchmark harnesses**: fixed prompts, temperature, and scoring scripts; compare **before/after** model ID, inference profile, or decoding settings.
- **When it matters:** model swap, quantization, or prompt-template change—check for regressions in reasoning, compliance tone, or structured output formatting.

---

### Behavioral & safety evals (the “guardrail layer”)

**Misuse resistance** and **policy compliance** in the **product/system** (prompting, tools, UX)—not the same as raw model benchmark scores.

#### 1) Attack & stress suites

- **Red teaming / prompt injection**: override instructions, secret exfiltration, coerced unsafe tool calls.
- **Toxicity / bias**: baited prompts; measure refusal quality and non-escalation.
- **PII handling**: paste SSNs, account numbers, etc.—refuse, redact, or route safely.

#### 2) Success criteria (“what good looks like”)

- **Refusal + safe alternative** (when appropriate), not only silence.
- **No secret leakage** (API keys, internal prompts, raw tool payloads).
- **Stable behavior under paraphrase** (same attack, different wording).

#### 3) How to measure (behavioral)

- **Curated suites** in CI: fixed adversarial prompts + expected behaviors (refuse, deflect, escalate to human).
- **Periodic red-team cycles** with logging and human review of failures.

---

### Operational & system evals (the “infrastructure”)

Whether the system is **healthy under load** and **affordable**.

#### 1) Performance & economics

- **Latency**: time-to-first-token (TTFT) where streaming applies; end-to-end task latency.
- **Cost efficiency**: tokens or dollars per **successful** task (especially for agent loops).
- **Throughput & backpressure**: queue depth, oldest-message age, concurrency limits, throttles, saturation.

#### 2) Reliability & operations

- **Error budgets**: HTTP/Lambda error rates, DLQ rates, partial failure modes.
- **SLOs & alarms**: p95/p99 latency, cost alarms, incident-ready dashboards.

---

### Summary table: which eval when?

| Category | Primary goal | Key question |
|---|---|---|
| **LLM eval** | Model capability | Is the “brain” good enough for the task *in isolation*? |
| **RAG eval** | Factuality + grounding | Did it find the right evidence and stay faithful to it? |
| **Agent eval** | Autonomy | Did it choose tools correctly and finish the task reliably? |
| **System eval** | Performance + economics | Is it fast, cheap, and stable under real traffic? |

---

### The “LLM-as-a-judge” trend

Across all categories, teams increasingly use **LLM-as-a-judge** with explicit rubrics (instead of only BLEU/ROUGE-style string similarity). A stronger “teacher” model grades outputs for faithfulness, logic, tone, policy compliance—**but** you should still add deterministic checks where possible (schemas, tool argument validators, golden tests).

---

## Summary: popular Python-oriented frameworks (when to use what)

| Framework | Best for | Why teams pick it |
|---|---|---|
| **Ragas** | RAG quality metrics | Convenient starting point for faithfulness/context-style scoring workflows |
| **DeepEval** | Unit-test style LLM evals | Feels like `pytest` for LLM/agent tests; good for CI gates |
| **LangSmith** | Trace review + human grading | Strong UI for inspecting runs, annotating failures, building datasets over time |

These are **not mutually exclusive**—many teams use **LangSmith for observability** + **DeepEval/Ragas for automated gates**.

---

## Practical code examples (three “bring it to life” patterns)

These examples are meant to show the **shape** of real eval code: a judge-backed **faithfulness** check (RAG), a **tool-use correctness** check (agentic), and a lightweight **LLM-as-judge** rubric (custom). Library APIs evolve—treat anything vendor-specific as a template and confirm against the library docs for your pinned versions.

**Dependency note:** keep eval dependencies isolated from production Lambda packages. In a local `uv` project, you’d typically `uv add ragas` / `uv add deepeval` in an **eval harness** folder—not inside `backend/api` unless you truly want them bundled.

### Example 1 — RAG eval: faithfulness / groundedness (Ragas-style)

**Goal:** score whether the model answer is actually **supported by** retrieved contexts (catch “confident hallucinations”).

```python
import asyncio

from ragas.metrics import faithfulness
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import langchain_llm_factory

# 1) Judge model (often stronger than your app model)
evaluator_llm = langchain_llm_factory("gpt-4o")

# 2) One sample: user question + retrieved contexts + model answer
sample = SingleTurnSample(
    user_input="When was the company founded?",
    retrieved_contexts=["The company was established in 1994 by Alex in a garage."],
    response="It was founded in 1994 by Alex.",
)

# 3) Score faithfulness for that single turn
scorer = faithfulness(llm=evaluator_llm)

async def main() -> None:
    score = await scorer.single_turn_ascore(sample)
    print(f"Faithfulness score: {score}")

if __name__ == "__main__":
    asyncio.run(main())
```

**How to interpret the score**

- **High faithfulness**: every concrete claim in the answer is entailed by the retrieved contexts.
- **Low faithfulness**: the answer adds facts, numbers, entities, or causal claims not present in context.

---

### Example 2 — Agentic eval: tool correctness (DeepEval-style)

**Goal:** treat tool calling like unit tests—did the agent pick the right tool and pass acceptable arguments?

```python
from deepeval.metrics import ToolCorrectnessMetric
from deepeval.test_case import LLMTestCase, ToolCall

expected_tools = [
    ToolCall(name="get_weather", arguments={"location": "San Francisco"}),
]

actual_tools = [
    ToolCall(name="get_weather", arguments={"location": "SF"}),
]

metric = ToolCorrectnessMetric(expected_tools=expected_tools)

test_case = LLMTestCase(
    input="What is the weather in San Francisco?",
    actual_output="It is 65 degrees in SF.",
    tools_called=actual_tools,
)

metric.measure(test_case)
print(f"Tool correctness score: {metric.score}")
print(f"Reason: {metric.reason}")
```

**What this is really testing**

- **Selection**: correct tool name for the intent.
- **Arguments**: schema-valid JSON *and* semantically acceptable values (SF vs San Francisco is a classic fuzzy-match problem—your metric/policy decides what counts).

---

### Example 3 — Custom eval: LLM-as-a-judge rubric (no framework required)

**Goal:** score subjective dimensions (tone, helpfulness, compliance) with an explicit rubric and structured output.

```python
import json
from typing import Any

def judge_helpfulness(*, user_query: str, agent_response: str, llm_json_completion) -> dict[str, Any]:
    prompt = f"""
You are an evaluator. Grade helpfulness only.

User query:
{user_query}

Agent response:
{agent_response}

Score 1-5:
1 = not helpful / incorrect
5 = excellent

Return JSON ONLY:
{{"score": <int>, "reason": "<string>"}}
""".strip()

    raw = llm_json_completion(prompt)  # implement: call OpenAI/Bedrock/etc.
    return json.loads(raw)
```

**Production tip:** keep the rubric stable, version it, and log `(score, reason, prompt_hash, model_id)` for auditability.

---

## Which eval should you implement first?

- **If you have RAG / retrieval in the loop:** start with **faithfulness + context precision/recall** (Ragas is a good first step).
- **If you have multi-tool agents:** start with **tool correctness + golden trajectories** (DeepEval-style tests are great CI gates).
- **If you’re live in production:** add **trace grading** (LangSmith / LangFuse) so failures become dataset rows, not one-off surprises.

---

## How this maps to Alex (concrete implementation hooks)

Alex is not a single chat box: **ingestion + S3 Vectors** (Guide 3), **Researcher on App Runner** (Guide 4), **Aurora + jobs** (Guide 5), and **Planner + specialist Lambdas** (Guide 6) with **FastAPI** (Guide 7). Evals attach to **those components**, not to a generic “RAG app” abstraction.

---

### RAG evals (where they land in *this* repo)

| Piece in Alex | Code / entry points | What to measure |
|---------------|---------------------|-----------------|
| **Vector index + search API** | Ingest/search Lambda `backend/ingest/search_s3vectors.py`; local harness `backend/ingest/test_search_s3vectors.py` | **Retrieval:** recall/precision/MRR/nDCG@k vs labeled queries (you need gold relevance labels or gold chunk keys in vector metadata). |
| **Reporter “RAG tool”** | `get_market_insights` in `backend/reporter/agent.py` — embeds a query from portfolio **symbols**, calls `s3vectors.query_vectors` on bucket `alex-vectors-{account_id}`, index `financial-research`, **topK=3**, returns concatenated metadata `text` snippets to the model | **Retrieval:** same metrics if you log returned `vector['key']` / metadata IDs. **Generation:** faithfulness of the *final report* vs the **exact string** returned by the tool (today the tool output is not persisted separately from the report—you’d add a structured log or DB field if you want automated faithfulness without re-querying). |
| **Researcher service** | `backend/researcher/server.py` — `POST /research` with `ResearchRequest.topic`; agent uses **MCP (Playwright)** + `ingest_financial_document` tool | **End-to-end:** quality of research memo; **ingestion** side tested via ingest pipeline. Grounding evals need either logged sources or replay of ingested docs. |

**Practical workflow (recommended order):**

1. **Retrieval-only (cheap):** extend `test_search_s3vectors.py` (or a new `uv` eval package) with a CSV of `(query, relevant_keys_or_metadata_ids)` and compute MRR / precision@k against live or staging index—same clients as production (`sagemaker-runtime` + `s3vectors`).
2. **Reporter faithfulness (deeper):** either (a) extend the existing judge in `backend/reporter/judge.py` with an explicit *“every numeric claim must appear in the tool-supplied context”* rubric, and pass the **market insights tool output** into the judge payload, or (b) log `retrieved_snippets` on the job row and run an offline Ragas `faithfulness` job in CI (see earlier example in this doc)—**without** adding heavy deps to the Lambda package unless you accept larger deploy artifacts.
3. **Regression gate:** pin a small golden set of symbols + queries after you change chunking, embedding endpoint, or `topK`.

---

### Agentic evals (orchestration + specialists)

| Stage | Code / entry points | What to measure |
|-------|---------------------|-----------------|
| **Job enqueue** | `POST /api/analyze` in `backend/api/main.py` — creates a row via `db.jobs.create_job`, sends **SQS** (`SQS_QUEUE_URL`) with `job_id` | API returns `job_id`; optional load test on queue depth (ops eval). |
| **Orchestrator** | `backend/planner/lambda_handler.py` (SQS `Records[0].body` → `run_orchestrator`); tools in `backend/planner/agent.py` — `invoke_reporter`, `invoke_charter`, `invoke_retirement` call Lambdas named by `REPORTER_FUNCTION`, `CHARTER_FUNCTION`, `RETIREMENT_FUNCTION`; **`MOCK_LAMBDAS`** for local | **Trajectory:** which tools ran and in what order (from **CloudWatch** / OpenTelemetry spans under `trace("Planner Orchestrator")`, or from Agents SDK run messages if you log them). **Golden test:** `backend/planner/test_simple.py` sets `MOCK_LAMBDAS=true` and drives `lambda_handler` with a real `job_id` from `reset_db.py`—extend assertions to expected **terminal job status** and mocked call counts if you wrap `invoke_lambda_agent`. |
| **Tagger (pre-planner)** | `handle_missing_instruments` in `backend/planner/agent.py` — synchronous `lambda_client.invoke(TAGGER_FUNCTION, …)` | **Outcome:** instruments gain allocation fields in DB; tagger `test_simple.py` / `test_full.py` patterns. |
| **Reporter outcome** | `backend/reporter/lambda_handler.py` — `Runner.run` then optional **`judge.evaluate`** (`backend/reporter/judge.py`), then `db.jobs.update_report` | **Outcome:** report JSON payload shape; **judge score** distribution in logs/LangFuse-style exporters if enabled. |
| **Charter outcome** | `backend/charter/lambda_handler.py` — parses JSON with top-level **`charts`** array, persists chart dict keyed by `chart['key']` | **Schema eval:** JSON Schema or `json.loads` + required keys (`key`, chart type fields your UI expects)—good CI fixture with a frozen portfolio snapshot. |
| **Retirement outcome** | `backend/retirement/lambda_handler.py` (same job_id pattern) | **Outcome:** stored projection fields / narrative as defined by your DB schema—assert on `test_simple` golden job. |

**Practical workflow:**

- **Local / CI (fast):** run `backend/*/test_simple.py` with `MOCK_LAMBDAS=true` and seeded DB (`backend/database`, `uv run reset_db.py --with-test-data`) to assert **job completion** and **DB artifacts** (report/charts) without AWS Lambdas.
- **Deployed (realistic):** `backend/planner/test_full.py` and sibling `test_full.py` files invoke real Lambdas—use for **trajectory + latency** after infra changes.
- **Strict tool order:** only assert order when product requires it; otherwise prefer **set-of-tools + final state** to avoid brittle tests when the planner legitimately reorders.

---

### Safety & policy evals (where user input actually enters)

| Surface | How it reaches the model | Eval idea |
|---------|--------------------------|-----------|
| **Analysis trigger** | `AnalyzeRequest` in `backend/api/main.py` includes **`options: Dict[str, Any]`** — anything the frontend sends there becomes orchestration context eventually | CI: `POST /api/analyze` with `options` containing injection strings; assert **no secret leakage** in logs/report, no unintended tool payloads, job still fails safe. |
| **Research topic** | `ResearchRequest.topic` → string in `run_research_agent` query (`backend/researcher/server.py`) | Same: malicious `topic` strings; assert refusal / no exfiltration of system prompt from HTTP responses. |
| **Portfolio-derived strings** | Symbols and names from **user-owned** accounts/positions flow into planner/reporter **task text** (see `load_portfolio_summary` / reporter task builders) | Golden user with positions whose **names** look like attacks; assert report still follows `backend/reporter/templates.py` style and disclaimers. |
| **Reporter quality gate** | `judge.evaluate` already scores 0–100; `lambda_handler` normalizes to 0–1 and **replaces** the user-visible report when that score is below `GUARD_AGAINST_SCORE` (0.3) — see `backend/reporter/lambda_handler.py` | Treat the judge as a **policy rubric hook**: extend `Evaluation` / instructions in `judge.py` for finance-specific rules (disclaimer present, no “guaranteed return” language), not only generic “quality.” |

**Practical workflow:**

- Maintain something like `evals/fixtures/adversarial.json` listing payloads for `options`, `topic`, and weird instrument names; a small `uv run` script calls the API (staging) with a test Clerk token or test user and asserts response shape plus forbidden substrings.
- Add **PII canaries** (fake account numbers) only in **non-prod** tenants or synthetic DB rows—never real PII in repo.

---

### Summary: smallest “Alex-shaped” eval MVP

1. **Retrieval:** script next to `test_search_s3vectors.py` with labeled queries → MRR@5.  
2. **Agent:** extend `planner/test_simple.py` to assert **job status** + **report row exists** after run (mocked Lambdas).  
3. **Safety:** five adversarial `options` / `topic` strings in CI against staging API.  
4. **Reporter quality:** tune `backend/reporter/judge.py` prompts and monitor judge scores in CloudWatch (already wired in the reporter path when observability is on).

---

## Next steps (if you want to operationalize this)

- Build a **golden dataset** (small, high-quality): questions, expected tool traces, expected payload shapes, and “must cite context” cases.
- Start with **5–20 evals in CI** that protect regressions (faithfulness + one injection suite + one tool-trace test).
- Use traces (e.g., LangSmith) to **mine failures** into new golden cases.
