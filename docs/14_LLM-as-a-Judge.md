# LLM-as-a-Judge in Alex: Fundamentals → Implementation → Production Use

This document explains **LLM-as-a-judge** (a.k.a. *model-based evaluation*) and how it’s implemented in this repo, specifically in `backend/reporter/judge.py` and `backend/reporter/lambda_handler.py`.

---

## What “LLM-as-a-judge” means (basics)

In many LLM apps, you have **an LLM that produces an output** (report/answer/plan). But you also need a way to measure if that output is “good enough”.

**LLM-as-a-judge** is a pattern where you run a *second* LLM call to **grade** the first output using a rubric. The judge typically returns:

- **A numeric score** (e.g., 0–100)
- **A rationale / feedback** (why it scored that way)
- Optionally **dimension scores** (clarity, correctness, safety, etc.)

### Why teams use it

- **Quality control**: detect bad outputs automatically.
- **Monitoring**: track quality drift after model/prompt changes.
- **Guardrails**: block or degrade gracefully when outputs are low-quality.
- **Dataset creation**: turn real production outputs into scored examples for regression tests.

### What it is *not*

- It’s **not ground truth**. It’s a *heuristic* signal.
- It doesn’t automatically guarantee correctness—especially for factual claims—unless your rubric requires grounding in evidence.

---

## A quick mental model: Producer vs Judge

```text
   (Producer LLM)                               (Judge LLM)
   ------------------                           -------------------
   input + context                               instructions + rubric
         |                                              |
         v                                              v
   model output  ----------------------------->  evaluation(score, feedback)
         |                                              |
         +-------------------- app uses ----------------+
                    (log / gate / retry / fallback)
```

---

## How the pattern is used in this repo (high level)

In Alex, the **Reporter agent** generates a markdown portfolio report. Right after that, we run a **Judge agent** to score the report quality.

### End-to-end flow (ASCII diagram)

```text
User / API
   |
   v
Planner Lambda  (backend/planner/lambda_handler.py)
  - loads job + portfolio summary
  - invokes specialist Lambdas (reporter/charter/retirement)
   |
   v
Reporter Lambda (backend/reporter/lambda_handler.py)
  - runs Reporter Agent to generate markdown report
  - calls Judge Agent (backend/reporter/judge.py)
  - logs score/feedback to observability (LangFuse, if configured)
  - if score too low -> replace with safe fallback message
  - saves final report to DB
```

---

## The “judge” implementation here (from basics to code)

### 1) Structured output: the `Evaluation` schema

In `backend/reporter/judge.py`, the judge returns a typed object:

- `feedback: str` (free-text explanation)
- `score: float` (0–100)

This is implemented as a Pydantic model (`Evaluation`). In the OpenAI Agents SDK, passing `output_type=Evaluation` means:

- the judge LLM is instructed to produce that structure
- the runtime parses/validates the final output into `Evaluation`

This reduces “random text” responses and makes the result easy to consume in code.

### 2) The judge prompt (“rubric”)

The judge’s `instructions` tell it:

- It is an **Evaluation Agent**
- It evaluates a **financial report** produced by another agent

The judge’s `task` includes:

- the original instructions given to the reporter (`REPORTER_INSTRUCTIONS`)
- the reporter’s task string (portfolio summary + requested sections)
- the reporter’s generated output (the markdown report)

This is critical: the judge grades the output **in the context of what was asked**.

### 3) The judge model & Bedrock configuration

This repo uses **AWS Bedrock through LiteLLM**, wired via:

- `LitellmModel(model=f"bedrock/{model_id}")`

And it sets the required env var for LiteLLM Bedrock:

- `AWS_REGION_NAME = BEDROCK_REGION`

The judge defaults to:

- `BEDROCK_MODEL_ID` default: `us.anthropic.claude-3-7-sonnet-20250219-v1:0`
- `BEDROCK_REGION` default: `us-west-2`

This matches the same pattern used by other agents in this repo (planner/reporter).

---

## Where the judge is called and what happens with the score

### The call site: Reporter Lambda

In `backend/reporter/lambda_handler.py`, after the Reporter agent produces `response` (the markdown report), the code:

1. Calls the judge:
   - `evaluation = await evaluate(REPORTER_INSTRUCTIONS, task, response)`
2. Normalizes to 0–1:
   - `score = evaluation.score / 100`
3. Logs to observability (when LangFuse is configured)
4. Applies a guardrail:
   - if `score < GUARD_AGAINST_SCORE` (0.3), replace the report with a safe failure message

### Why the “guardrail” exists

In production, you generally want:

- **No silently-bad reports** saved and shown to users
- A stable user experience even during model regressions, rate-limit issues, partial outages, or tool failures

So the judge becomes a **quality gate**.

---

## How observability fits in (why the judge score matters)

The judge score is especially useful when you can see it alongside:

- model ID + region
- latency
- retries / rate-limit behavior
- job_id / user_id (careful with PII)
- upstream tool calls (e.g., reporter’s `get_market_insights`)

In this repo, `backend/reporter/observability.py` conditionally enables LangFuse exporting when `LANGFUSE_SECRET_KEY` is set. When enabled, the reporter records a “judge” span with:

- the normalized score
- feedback (comment)

This turns “the report felt bad” into something observable and monitorable.

For the complete end-to-end “where traces come from and how to find them in Langfuse” walkthrough, see `docs/Observability-langfuse.md`.

---

## Common judge designs (theory → advanced)

### A) Single overall score (what you have now)

Pros:
- simple to implement and reason about
- easy to gate on

Cons:
- hard to debug: “why 62?” mixes many dimensions

### B) Multi-dimension rubric (recommended next step)

Example dimensions:
- **Correctness** (within given data)
- **Clarity** (readable for retail investors)
- **Actionability** (specific recommendations)
- **Safety/compliance** (no “guaranteed returns”, includes disclaimers)
- **Groundedness** (claims supported by provided portfolio + retrieved context)

This helps you identify whether failures are mainly *style* vs *truthfulness* vs *missing content*.

### C) Pairwise comparison (A/B testing)

Instead of absolute score, the judge compares **output A vs output B** and selects the better one given a rubric.

This is often more stable than absolute scores when you’re evaluating prompt changes.

---

## Risks / pitfalls (important in production)

### 1) Judge bias and “reward hacking”

The generator can learn to produce outputs that *look good to the judge* rather than being correct.

Mitigations:
- keep rubrics explicit and test them against adversarial cases
- spot-check with humans
- add deterministic checks where possible (schemas, required sections)

### 2) Correlated errors (same model family judges itself)

If the producer and judge are very similar models, they can share blind spots.

Mitigations:
- use a stronger/different judge model
- or add evidence-based checks (e.g., “every numeric claim must appear in supplied data”)

### 3) Non-determinism and drift

Judge outputs can vary with temperature/model updates.

Mitigations:
- fix model IDs and configuration
- log judge prompt version
- create a small “golden” eval set and track score distributions over time

### 4) Latency and cost

Judge adds another LLM call. In agentic flows, this can be meaningful.

Mitigations:
- judge only on certain jobs (sampled monitoring)
- judge only when a quick heuristic suggests risk (e.g., missing sections)
- keep max_turns low (this repo uses `max_turns=5`)

---

## How to read `backend/reporter/judge.py` (line-by-line intent)

At a high level, `evaluate(original_instructions, original_task, original_output)` does:

- **Build judge context** (instructions + task + output)
- **Create a Judge Agent** with structured output (`output_type=Evaluation`)
- **Run** it via `Runner.run(...)`
- **Return** the parsed `Evaluation`
- **Fallback** to a default score (80) if judging fails (to avoid breaking the reporter pipeline)

That fallback choice is a tradeoff:

- it prevents system failure if the judge call errors
- but it may hide judge outages (you’ll want to monitor judge exceptions in logs)

---

## Where this is packaged/deployed

The judge code is shipped with the reporter Lambda package. You can see it explicitly included here:

- `backend/reporter/package_docker.py` copies `judge.py` into the Lambda zip.

So operationally:

- Judge runs **inside** the reporter Lambda runtime (not a separate service).

---

## Practical next improvements (optional, but “advanced and valuable”)

If you want the judge to be more finance-relevant and safer, common upgrades are:

- **Add required checks to the rubric**: must include disclaimers, must avoid “guaranteed returns”, must not invent prices.
- **Pass tool outputs to the judge**: include the exact `get_market_insights()` return text so the judge can score *groundedness*.
- **Return structured per-section scoring**: score each required section so missing sections are obvious.
- **Write scores to the DB** (not just observability) so UI can show “confidence/quality”.

---

## File map (what to read next)

- **Judge**: `backend/reporter/judge.py`
- **Reporter calls judge + guardrail**: `backend/reporter/lambda_handler.py`
- **Reporter tool (RAG)**: `backend/reporter/agent.py` (`get_market_insights`)
- **Reporter instructions**: `backend/reporter/templates.py`
- **Planner orchestrates**: `backend/planner/lambda_handler.py`, `backend/planner/agent.py`
- **Evals background**: `docs/10_EVALs.md` (taxonomy; judge concept overview)

