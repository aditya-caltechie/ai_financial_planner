# Guardrails — Basics and how Alex implements them

This doc explains **guardrail fundamentals** (from `guides/8_enterprise.md` Section 4) and maps them to **real implementations in this repo** under `backend/`.

Guardrails are “safety checks” around AI: they reduce the chance that an LLM mistake becomes a **user-visible incident**, a **bad database write**, or a **runaway cost spike**.

---

## 1) Guardrails: the basic idea (mental model)

Think of an agent pipeline like this:

```text
inputs -> agent run (LLM + tools) -> output -> persist -> user sees it
```

Guardrails are checks you add at key points:

- **Input guardrails**: validate/sanitize inputs before they reach prompts/tools
- **Runtime guardrails**: cap turns/time, retry transient failures, prevent infinite loops
- **Output guardrails**: validate output shape (JSON schema, required keys), reject/fallback
- **Quality guardrails**: use scoring (human or LLM judge) to block low-quality results

In production you usually combine multiple guardrails. No single check is enough.

---

## 2) What the Guide suggests (8_enterprise.md:480–657)

The guide lists these guardrail patterns:

- **Charter output validation**: ensure the charter agent returns valid JSON with the expected schema (charts array, type/data fields).
- **Input validation guardrails**: sanitize text to reduce prompt injection.
- **Response size limits**: truncate overly-large outputs to avoid runaway cost and payload bloat.
- **Retry logic with exponential backoff**: use `tenacity` beyond rate-limits (timeouts, throttling).

Below is how these ideas show up **in this repo today**.

---

## 3) Output guardrail (implemented): Charter “JSON extraction + parse” validation

### Why it’s needed

The Charter agent is expected to output **JSON** describing charts. In practice, LLMs sometimes wrap JSON in extra text, omit braces, or return invalid JSON. If you store invalid chart payloads, the UI breaks.

### How it’s implemented in this repo

`backend/charter/lambda_handler.py` implements a pragmatic output guardrail:

- Finds the first `{` and last `}` in the agent output
- Attempts `json.loads(...)`
- Extracts `charts`
- If parsing fails or `charts` is empty, it logs errors/warnings and returns a failure response

Code reference:

```37:125:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/charter/lambda_handler.py
async def run_charter_agent(job_id: str, portfolio_data: Dict[str, Any], db=None) -> Dict[str, Any]:
    """Run the charter agent to generate visualization data."""
    
    # Create agent without tools - will output JSON
    model, task = create_agent(job_id, portfolio_data, db)
    
    # Run agent - no tools, no context
    with trace("Charter Agent"):
        agent = Agent(
            name="Chart Maker",
            instructions=CHARTER_INSTRUCTIONS,
            model=model
        )
        
        result = await Runner.run(
            agent,
            input=task,
            max_turns=5  # Reduced since we expect one-shot JSON response
        )
        
        # Extract and parse JSON from the output
        output = result.final_output
        # ...
        start_idx = output.find('{')
        end_idx = output.rfind('}')
        if start_idx >= 0 and end_idx > start_idx:
            json_str = output[start_idx:end_idx + 1]
            parsed_data = json.loads(json_str)
            charts = parsed_data.get('charts', [])
            # ...
```

### What’s missing vs the guide’s “ideal” schema validation

The guide proposes a stricter `validate_chart_data()` function that checks:

- `"charts"` exists
- charts is a list
- each chart has expected fields like `type`, `data`, and per-type point fields

**That stricter schema check is not implemented yet** in the current Charter handler. Today’s version mostly ensures:

- “can we parse JSON?”
- “does it contain `charts`?”

This is still valuable (prevents obvious breakages) but the next step would be to add **schema-level checks**.

---

## 4) Quality guardrail (implemented): Reporter “LLM-as-a-judge” scoring gate

### Why it’s needed

A report can be syntactically valid markdown but still be “bad” (missing sections, unhelpful, incoherent, unsafe claims). A quality guardrail blocks that from reaching the user.

### How it’s implemented in this repo

The Reporter Lambda runs a second LLM call as a **judge** and uses its score to decide whether to return the report to the user.

Key pieces:

- `backend/reporter/judge.py` defines a structured `Evaluation` result with:
  - `feedback: str`
  - `score: float` (0–100)
- `backend/reporter/lambda_handler.py`:
  - runs the reporter agent
  - calls `evaluate(...)`
  - normalizes score to 0–1
  - if score < `GUARD_AGAINST_SCORE`, it **replaces** the report with a safe fallback message

Code reference (the gate + score logging):

```17:83:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/reporter/lambda_handler.py
GUARD_AGAINST_SCORE = 0.3  # Guard against score being too low

# ...
        if observability:
            with observability.start_as_current_span(name="judge") as span:
                evaluation = await evaluate(REPORTER_INSTRUCTIONS, task, response)
                score = evaluation.score / 100
                comment = evaluation.feedback
                span.score(name="Judge", value=score, data_type="NUMERIC", comment=comment)
                observation = f"Score: {score} - Feedback: {comment}"
                observability.create_event(name="Judge Event", status_message=observation)
                if score < GUARD_AGAINST_SCORE:
                    logger.error(f"Reporter score is too low: {score}")
                    response = "I'm sorry, I'm not able to generate a report for you. Please try again later."
```

Code reference (judge structured output):

```10:61:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/reporter/judge.py
class Evaluation(BaseModel):
    feedback: str = Field(
        description="Your feedback on the financial report and rationale for your score"
    )
    score: float = Field(
        description="Score from 0 to 100 where 0 represents a terrible quality financial report and 100 represents an outstanding financial report"
    )

async def evaluate(original_instructions, original_task, original_output) -> Evaluation:
    # ...
    agent = Agent(
        name="Judge Agent", instructions=instructions, model=model, output_type=Evaluation
    )
    result = await Runner.run(agent, input=task, max_turns=5)
    return result.final_output_as(Evaluation)
```

### What this guardrail protects

- **User experience**: avoids delivering a low-quality report.
- **Operational debugging**: the judge score + feedback are attached to traces when Langfuse is enabled.

### Tradeoff to understand

If the judge fails (exception), `judge.py` returns a default `Evaluation(..., score=80)` to avoid breaking the pipeline. That’s good for availability, but you should still monitor judge errors in CloudWatch logs.

---

## 5) Runtime guardrail (implemented): retries with exponential backoff (Tenacity)

### Why it’s needed

LLM calls and downstream services can hit transient issues:

- rate limits / throttling
- timeouts
- intermittent network failures

Retries with exponential backoff improve reliability without requiring user retries.

### Reporter: retry on Bedrock rate limiting

```37:44:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/reporter/lambda_handler.py
@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(
        f"Reporter: Rate limit hit, retrying in {retry_state.next_action.sleep} seconds..."
    ),
)
```

### Planner: retry on Bedrock rate limiting

```35:40:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/planner/lambda_handler.py
@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(f"Planner: Rate limit hit, retrying in {retry_state.next_action.sleep} seconds...")
)
```

### Retirement: retry on multiple “temporary” failures (more advanced)

Retirement defines `AgentTemporaryError` and retries on multiple transient error types, converting timeouts/throttling into retryable errors:

```17:103:/Users/averma/github/Udemy/02_AI-ML_Courses/my-github-projects/ai-financial-planner/backend/retirement/lambda_handler.py
class AgentTemporaryError(Exception):
    """Temporary error that should trigger retry"""
    pass

@retry(
    retry=retry_if_exception_type((RateLimitError, AgentTemporaryError, TimeoutError, asyncio.TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(f"Retirement: Temporary error, retrying in {retry_state.next_action.sleep} seconds...")
)
async def run_retirement_agent(job_id: str, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    # ...
    try:
        result = await Runner.run(agent, input=task, max_turns=20)
    except (TimeoutError, asyncio.TimeoutError) as e:
        raise AgentTemporaryError(f"Timeout during agent execution: {e}")
    except Exception as e:
        if "timeout" in str(e).lower() or "throttled" in str(e).lower():
            raise AgentTemporaryError(f"Temporary error: {e}")
        raise
```

---

## 6) Guardrails recommended by the guide (not yet implemented in `backend/`)

These patterns appear in `guides/8_enterprise.md`, but I did not find them implemented under `backend/` right now:

- **Input sanitization** (`sanitize_user_input(...)` pattern)
- **Response size limits** (`truncate_response(...)` pattern)
- **Strict Charter schema validation** (`validate_chart_data(...)` per chart/type structure)

They’re good next steps if you want stronger safety guarantees.

---

## 7) How guardrails connect to monitoring and observability

Guardrails should emit signals so you can see them in production:

- **CloudWatch Logs**: “guardrail triggered” events (e.g., JSON parse failed, judge score low)
- **CloudWatch Metrics/Alarms**: spikes in failures (errors, DLQ, queue age)
- **Langfuse**: attach scores/events to traces (example: the reporter’s `judge` span)

