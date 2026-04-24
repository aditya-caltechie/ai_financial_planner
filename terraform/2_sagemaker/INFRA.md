## `terraform/2_sagemaker` — SageMaker embeddings endpoint

This stack provisions the **SageMaker serverless inference endpoint** used to generate text embeddings for the ingest pipeline (Guide 2).

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| IAM | `alex-sagemaker-role` + `AmazonSageMakerFullAccess` attachment | Lets SageMaker create/operate the model + endpoint. |
| SageMaker | `alex-embedding-model` | HuggingFace inference container configured for `feature-extraction`. |
| SageMaker | `alex-embedding-serverless-config` | Serverless endpoint config (memory + max concurrency). |
| SageMaker | `alex-embedding-endpoint` | The endpoint ingest calls via `sagemaker:InvokeEndpoint`. |
| Terraform helper | `time_sleep.wait_for_iam_propagation` | Small delay to avoid IAM propagation race before endpoint create. |

---

## Key inputs

| Variable | Where | Meaning |
| --- | --- | --- |
| `aws_region` | `variables.tf` | Region to deploy the endpoint. |
| `sagemaker_image_uri` | `variables.tf` | HF PyTorch inference image URI (default points at `us-east-1`). |
| `embedding_model_name` | `variables.tf` | HF model id (default: `sentence-transformers/all-MiniLM-L6-v2`). |

---

## Outputs you’ll use later

| Output | Used by | Why |
| --- | --- | --- |
| `sagemaker_endpoint_name` | `terraform/3_ingestion`, `terraform/6_agents`, `.env` | Ingest + agents invoke this endpoint for embeddings. |

---

## ASCII flow

```
IAM role/policy
   |
   v
SageMaker Model  ->  Endpoint Configuration  ->  Serverless Endpoint
   (HF image)        (memory/concurrency)       (alex-embedding-endpoint)
```

---

## How Terraform builds it (in plain terms)

1. Creates an IAM role SageMaker can assume.
2. Creates a `aws_sagemaker_model` pointing at the HF inference image and sets env vars (`HF_MODEL_ID`, `HF_TASK`).
3. Creates a serverless endpoint configuration.
4. Waits ~15s for IAM propagation.
5. Creates the endpoint that later stacks will call.

