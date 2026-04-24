## `terraform/8_enterprise` — CloudWatch dashboards (enterprise monitoring)

This stack provisions CloudWatch **dashboards** that help you monitor:
- Bedrock model usage (invocations, token counts, latency, errors)
- SageMaker embedding endpoint usage and latency
- Agent Lambda duration and errors

It’s “enterprise” in the sense that it adds **operational visibility** rather than core functionality (Guide 8).

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| CloudWatch | Dashboard `alex-ai-model-usage` | Bedrock metrics + SageMaker endpoint invocations/latency. |
| CloudWatch | Dashboard `alex-agent-performance` | Lambda duration + error metrics for the agent suite. |

---

## Key inputs

| Variable | Meaning |
| --- | --- |
| `aws_region` | Region where Lambda/SageMaker metrics live. |
| `bedrock_region` | Region where Bedrock metrics live (can differ). |
| `bedrock_model_id` | ModelId string used in Bedrock metrics widgets. |

---

## ASCII flow

```
CloudWatch Dashboards
   |
   +--> Bedrock metrics (region = bedrock_region, modelId = bedrock_model_id)
   +--> SageMaker metrics (embedding endpoint)
   +--> Lambda metrics (alex-* functions)
```

---

## How Terraform builds it (in plain terms)

1. Creates dashboard JSON bodies with CloudWatch metric widgets.
2. Uses a mix of direct metrics (Bedrock, Lambda) and CloudWatch Logs Insights/SEARCH expressions (SageMaker widgets) to visualize endpoint usage.

