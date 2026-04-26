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
   | Retriever | ----------> | chunks / passages |
   +-----------+             +--------+---------+
         |                            |
  1) Retrieval metrics               | read as context
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
         +--------->| Tools / APIs / UI |
         |          +---------+--------+
         |                |
         |                v
  +------+------+   +--------------+    observe    +-------------+
  | Agent brain |   | Environment  |-------------->| State / DB  |
  +------+------+   +--------------+                +-------------+
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

## How this maps to Alex (so it’s not abstract)

- **RAG evals**: Research → ingest → vectors; then “did retrieval help the planner/reporter answer without inventing facts?”
- **Agentic evals**: Planner/specialists tool calls + job payload schemas + “did analysis complete?”
- **Safety evals**: Prompt injection attempts against user-provided text fields + finance disclaimers + PII handling

---

## Next steps (if you want to operationalize this)

- Build a **golden dataset** (small, high-quality): questions, expected tool traces, expected payload shapes, and “must cite context” cases.
- Start with **5–20 evals in CI** that protect regressions (faithfulness + one injection suite + one tool-trace test).
- Use traces (e.g., LangSmith) to **mine failures** into new golden cases.
