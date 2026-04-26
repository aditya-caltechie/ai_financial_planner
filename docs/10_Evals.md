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

### RAG evals (retrieval + grounding)

RAG evals focus on the **knowledge layer**: did we find the right evidence, and did the model stay anchored to it?

**Retrieval metrics (the search)**

- **Context recall**: did retrieval surface *enough* of the relevant evidence to answer the question?
- **Context precision**: of what was retrieved, how much was actually relevant? (noise contributes to “lost in the middle” failures)
- **MRR (mean reciprocal rank)**: where does the *first* relevant item appear in the ranked list? (classic “best hit” ranking quality)
- **nDCG (normalized discounted cumulative gain)**: rewards putting *multiple* relevant items high in the list, with diminishing credit deeper in the ranking—useful when users skim top‑k chunks or when several passages should be retrieved together.
- **MAP / precision@k / recall@k** (optional): common when you fix a cutoff *k* (e.g., top 5 chunks) and care about density of good hits in that window.

**When MRR vs nDCG:** use **MRR** if “any one gold passage near the top is enough”; use **nDCG** when **order and breadth** of relevant passages matter (multi-evidence questions, long contexts, reranking comparisons).

**Lexical signals (optional, dataset-dependent)**

- **Keyword coverage** (or similar): overlap between query/gold terms and retrieved text (or between gold answer and generation). Cheap and interpretable for keyword-heavy corpora; weak for paraphrase unless paired with semantic retrieval.

**Generation metrics (the answer)**

- **Faithfulness / groundedness**: is every substantive claim supported by retrieved context? (primary anti-hallucination check)
- **Answer relevance**: does the answer address the user’s question (even if retrieval was imperfect)?

**Answer rubrics (human or LLM-as-judge)** — often reported as 1–5 scores alongside retrieval metrics:

- **Accuracy** (name varies): factual correctness vs a **reference answer** or expert judgment—not the same as faithfulness unless the rubric ties claims to retrieved context.
- **Completeness**: whether required sub-facts or checklist items are covered.
- **Relevance**: alignment with user intent (overlaps with “answer relevance,” but is not the same as faithfulness to retrieved context).

**Why retrieval can improve while an “accuracy” score drops:** reranking / richer context can surface **conflicting** passages, add **noise** that hurts the reader model, or change **what the judge rewards** (e.g., stricter citation expectations). Treat that as a signal to separate **retrieval-only** runs from **end-to-end** runs and to add **faithfulness** checks—not only ranking metrics.

**How you score these (typical approaches)**

- **Retrieval scoring**: human labels, keyword/semantic overlap vs “gold” chunk IDs, or automated checks when you have structured ground truth.
- **Faithfulness**: LLM-as-judge with strict rubric, or libraries that implement judge prompts + scoring.
- **Answer relevance**: LLM-as-judge or task-specific rubric (finance apps often add domain constraints).

---
### Agentic evals (reasoning + action)

Agentic systems are closer to **loops** than one-shot pipelines: you evaluate planning, tool use, recovery, and end outcomes.

Think in **two layers** (similar spirit to RAG’s retrieval vs generation):

- **Trajectory / control layer**: *which* tools, *when*, with *what* arguments—often scored against golden traces or constraints.
- **Outcome / world layer**: *what changed* after the run—DB rows, job status, files, API side effects, and whether the user-visible result is correct.

**Tool use & function calling**

- **Tool selection accuracy**: correct tool for the intent (weather tool vs calculator)
- **Argument correctness**: right parameters + valid schema/format (exact match, fuzzy match for free text, or schema validator pass/fail)

**Trajectory shape metrics** (useful when you change prompting, planner, or tool set—same role as MRR/nDCG for ranking)

- **Strict sequence match**: predicted tool call chain equals gold (hard; brittle when multiple valid orderings exist).
- **Set overlap / precision–recall on tools**: did it call the *right set* of tools regardless of order? (good when order is flexible)
- **Prefix / “first error” metrics**: how many initial steps were correct before the first mistake? (analogous to “best relevant hit early” in retrieval)
- **Recovery quality**: after a tool error, does it backtrack, retry sensibly, or loop?

**Reasoning & planning**

- **Step efficiency**: did it solve the task in ~N steps vs thrashing for many steps (cost + reliability)?
- **Reasoning trace quality** (if logged): does the plan progress logically, or repeat failed approaches?

**Task completion (“bottom line”)**

- **Success rate**: percent of runs that reach a correct terminal state
- **Reliability / consistency**: repeated trials with the same task—does it succeed stably or behave stochastically?

**Outcome rubrics (human or LLM-as-judge)** — beyond pass/fail:

- **Helpfulness / clarity** of the final user-facing message (may pass functionally but read poorly).
- **Policy adherence**: did it avoid disallowed actions (e.g., calling a “write” tool without confirmation) even when the final artifact looks fine?

**When trajectory metrics vs outcome metrics:** use **trajectory** scores to debug *orchestration* regressions quickly; use **outcome + state assertions** for what production actually cares about. They can diverge: **better tool accuracy** but **worse user scores** if the agent adds redundant calls, picks a valid-but-suboptimal path, exposes ugly intermediate errors, or succeeds on a *different* acceptable trajectory your rubric penalized.

**How you score (typical approaches)**

- **Deterministic**: golden traces, JSON-schema validation on tool args, idempotency keys, DB snapshots, workflow state machines.
- **Probabilistic / judge**: LLM grades plan quality, explanation quality, or “did it follow house style?”—version the rubric and spot-check against humans.

**Practical “golden tests” for agents**

- **Golden trajectories**: for a fixed input, assert expected tool sequence (or acceptable alternatives).
- **State assertions**: DB rows written, job status transitions, payload schema validation (e.g., chart JSON).

---
### Foundation / LLM evals (the “brain”)

These are **model capability** evaluations *before* (or alongside) your product layer:

- **Knowledge benchmarks** (example family): broad multitask knowledge tests (e.g., MMLU-style suites)
- **Reasoning / code benchmarks** (example families): math word problems, coding exercises (e.g., GSM8K-style / HumanEval-style)

**Why this matters even if you use Bedrock models:** you still need to know whether a model swap (or temperature change) regresses reasoning, compliance, or formatting.

---
### Behavioral & safety evals (the “guardrail layer”)

These evals measure **misuse resistance** and **policy compliance** in the **product/system** (prompting, tools, UX), not just raw model capability.

**Common suites**

- **Red teaming / prompt injection**: attempt to override system instructions (“ignore previous instructions…”), exfiltrate secrets, or coerce unsafe tool calls.
- **Toxicity / bias**: baited prompts that try to elicit harmful content; measure refusal quality + non-escalation.
- **PII sensitivity**: does the system refuse/redact appropriately when users paste SSNs, account numbers, etc.?

**What “good” looks like**

- **Refusal + safe alternative** (when appropriate), not just silence
- **No secret leakage** (API keys, internal prompts, tool outputs)
- **Stable behavior under paraphrase attacks** (same attack, different wording)

---
### Operational & system evals (the “infrastructure”)

These measure whether the system is healthy in production:

- **Latency**: time-to-first-token (TTFT) where streaming applies; end-to-end turnaround for tasks
- **Cost efficiency**: tokens / dollars per successful task (especially for agent loops)
- **Throughput & backpressure**: queue depth / oldest message age, concurrency limits, throttles, saturation behavior

> Pair these with classic **SLOs** (p95/p99 latency, error rate, cost alarms) and incident-ready dashboards.

### Summary table: which eval when?

| Category | Primary goal | Key question |
|---|---|---|
| **LLM eval** | Model capability | Is the “brain” good enough for the task *in isolation*? |
| **RAG eval** | Factuality + grounding | Did it find the right evidence and stay faithful to it? |
| **Agent eval** | Autonomy | Did it choose tools correctly and finish the task reliably? |
| **System eval** | Performance + economics | Is it fast, cheap, and stable under real traffic? |

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
