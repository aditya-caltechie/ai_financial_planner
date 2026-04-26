# Evaluations (RAG, Agentic, Safety) — Practical Metrics + Examples

This note is a **clean mental model** for evaluating LLM systems in production. It maps naturally to Alex-style architectures where you have:

- **Retrieval** (S3 Vectors / embeddings / “what context did we fetch?”)
- **Agents** (tool calls, multi-step workflows, orchestration)
- **Safety** (prompt injection, PII, toxicity)

---

## 1) RAG evals (the “knowledge layer”)

RAG evaluations validate the **bridge** between private knowledge and the model: *did we retrieve the right stuff*, and *did the model stay anchored to it*?

### The “RAG triad” (common framing)

- **Context recall (retrieval coverage)**  
  Did retrieval surface the document(s) needed to answer the question?

- **Context precision (retrieval cleanliness)**  
  Was retrieved context mostly relevant, or noisy/irrelevant chunks that can confuse the model?

- **Faithfulness / groundedness (most important for RAG quality)**  
  Is the answer **supported by** the retrieved context (not mixing in unstated facts)?

- **Answer relevance**  
  Does the answer address the user’s question (even if it’s not the “best” answer), given the constraints of the context?

### How you score these (typical approaches)

- **Retrieval metrics**: human labels, keyword/semantic overlap vs “gold” chunk IDs, or automated checks when you have structured ground truth.
- **Faithfulness**: LLM-as-judge with strict rubric, or libraries that implement judge prompts + scoring.
- **Answer relevance**: LLM-as-judge or task-specific rubric (finance apps often add domain constraints).

---

## 2) Agentic evals (the “action layer”)

Agents are harder than plain chat because they **take actions** (tools, writes, orchestration). You evaluate **trajectories** and **tool use**, not only final text.

### Core metrics

- **Tool call accuracy**
  - **Selection**: did it pick the right tool (e.g., `get_weather` vs `calculate_tax`)?
  - **Arguments / schema**: valid JSON / correct parameter names / types?

- **Task success rate (binary pass/fail)**
  Did the agent reach a correct terminal state that satisfies the user request?

- **Efficiency (step count / cost)**
  If a task should take ~3 steps but takes ~15, penalize loops/thrashing (and watch token spend).

- **Reasoning consistency (optional, judge-based)**
  Does the chain-of-thought (if you log it) follow coherent logic, or does it “hallucinate progress”?

### Practical “golden tests” for agents

- **Golden trajectories**: for a fixed input, assert expected tool sequence (or acceptable alternatives).
- **State assertions**: DB rows written, job status transitions, payload schema validation (e.g., chart JSON).

---

## 3) Behavioral & safety evals (the “guardrail layer”)

These evals measure **misuse resistance** and **policy compliance**, not just correctness.

### Common suites

- **Red teaming / prompt injection**
  Attempt to override system instructions (“ignore previous instructions…”), exfiltrate secrets, or coerce unsafe tool calls.

- **Toxicity / bias**
  Baited prompts that try to elicit harmful content; measure refusal quality + non-escalation.

- **PII sensitivity**
  Does the system refuse/redact appropriately when users paste SSNs, account numbers, etc.?

### What “good” looks like

- **Refusal + safe alternative** (when appropriate), not just silence
- **No secret leakage** (API keys, internal prompts, tool outputs)
- **Stable behavior under paraphrase attacks** (same attack, different wording)

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
