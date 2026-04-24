## `terraform/6_agents` — SQS orchestration + agent Lambdas

This stack provisions the **async orchestration plane** (Guide 6):
- one SQS queue (plus DLQ) for jobs
- five Lambda functions (planner/tagger/reporter/charter/retirement)
- IAM permissions for those Lambdas to access Bedrock, Aurora Data API, vectors, etc.
- an S3 bucket for large Lambda deployment packages (packages > 50 MB).

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| SQS | `alex-analysis-jobs` + `alex-analysis-jobs-dlq` | Work queue for analysis requests; DLQ for retries. |
| IAM | `alex-lambda-agents-role` + inline policy + basic execution policy | Lets agent Lambdas read/write Aurora (Data API), query vectors, invoke Bedrock, call other Lambdas, etc. |
| S3 (standard) | `alex-lambda-packages-<account-id>` | Stores Lambda zip artifacts for deployment via S3. |
| S3 objects | `planner/...`, `tagger/...`, ... | Uploads zip files from `backend/<agent>/<agent>_lambda.zip`. |
| Lambda | `alex-planner`, `alex-tagger`, `alex-reporter`, `alex-charter`, `alex-retirement` | The multi-agent Lambda functions. |

---

## Prerequisites / dependencies

| Dependency | Why |
| --- | --- |
| Zips built locally | Terraform uploads zip files from `backend/<agent>/<agent>_lambda.zip`. You must run `backend/package_docker.py` first. |
| `terraform/5_database` applied | Needs `aurora_cluster_arn` and `aurora_secret_arn` inputs. |
| S3 Vector bucket exists | Needs `vector_bucket` input (console-created). |
| Bedrock model access | Lambdas call Bedrock using `bedrock_model_id` / `bedrock_region`. |
| SageMaker endpoint exists | Uses `sagemaker_endpoint` input for embeddings (reporter). |

---

## Key inputs (selected)

| Variable | Meaning |
| --- | --- |
| `aurora_cluster_arn`, `aurora_secret_arn` | Data API + secret for DB reads/writes. |
| `vector_bucket` | S3 Vector bucket name (console-created). |
| `bedrock_model_id`, `bedrock_region` | Bedrock model configuration for all agents. |
| `polygon_api_key`, `polygon_plan` | Market data access. |
| `sagemaker_endpoint` | Embedding endpoint name (defaults to `alex-embedding-endpoint`). |
| `langfuse_*`, `openai_api_key` | Observability/tracing knobs. |

---

## Outputs you’ll use later

| Output | Used by | Why |
| --- | --- | --- |
| `sqs_queue_url` / `sqs_queue_arn` | `terraform/7_frontend` + API code | API submits jobs to this queue; IAM policies reference ARN. |
| `lambda_functions` | Humans/tests | Handy listing of deployed Lambda names. |

---

## ASCII flow

```
API / users
   |
   v
SQS queue alex-analysis-jobs  ---> Planner Lambda (alex-planner)
                                     |
                                     | invokes
                                     v
                          Tagger / Reporter / Charter / Retirement
                                     |
                                     +--> Aurora Data API (cluster ARN + secret)
                                     +--> Bedrock (model inference)
                                     +--> S3 Vectors API (query/get)
                                     +--> Polygon / SageMaker (as configured)
```

---

## How Terraform builds it (in plain terms)

1. Creates SQS queue + DLQ with a redrive policy.
2. Creates a shared IAM role/policy for all agent Lambdas.
3. Creates an S3 bucket for Lambda package storage, then uploads each zip as an S3 object.
4. Creates each Lambda pointing at the S3 object key and wiring environment variables from `terraform.tfvars`.

