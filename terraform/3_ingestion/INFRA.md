## `terraform/3_ingestion` — ingest API + Lambda (and a standard S3 bucket)

This stack provisions the **ingest Lambda** and an **API Gateway REST API** endpoint that accepts text, calls SageMaker embeddings, and writes vectors via the S3 Vectors API (Guide 3).

Important naming nuance:
- This stack also creates a **standard S3 bucket** named like `alex-vectors-<account-id>`.
- The course’s **S3 Vector bucket + index** (S3 → *Vector buckets*) is a **different** resource type; it is **manual** in the console in this repo.

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| S3 (standard) | `alex-vectors-<account-id>` + encryption + versioning + public-access block | Stores ingest artifacts / supports permissions; also used as the bucket name in `VECTOR_BUCKET` env for the ingest lambda in this stack. |
| IAM | `alex-ingest-lambda-role` + inline policy | Grants CloudWatch Logs, S3, `sagemaker:InvokeEndpoint`, and `s3vectors:*` actions needed by ingest. |
| Lambda | `alex-ingest` | Runs the ingest handler from the packaged zip. |
| CloudWatch | `/aws/lambda/alex-ingest` log group | Central logs for ingest lambda. |
| API Gateway (REST) | `alex-api` + `/ingest` POST method + Lambda proxy integration | Public HTTP endpoint for ingest, protected with an API key. |
| API Gateway (usage) | API key + usage plan + plan key | Basic throttling/quota + API key auth. |

---

## Prerequisites / dependencies

| Dependency | Why |
| --- | --- |
| `terraform/2_sagemaker` applied | You must provide `sagemaker_endpoint_name` so ingest can call embeddings. |
| Ingest zip built locally | `backend/ingest/package.py` must create `backend/ingest/lambda_function.zip` before `terraform apply`. |

---

## Key inputs

| Variable | Meaning |
| --- | --- |
| `aws_region` | Region to deploy. |
| `sagemaker_endpoint_name` | Endpoint name from `terraform/2_sagemaker` output. |

---

## Outputs you’ll use later

| Output | Used by | Why |
| --- | --- | --- |
| `api_endpoint` | `.env`, Researcher | Researcher posts docs to this endpoint. |
| `api_key_id` / `api_key_value` | `.env`, Researcher | API key required for ingest requests. |
| `vector_bucket_name` | `.env` / later stacks | Bucket name created by this stack (standard S3). |

---

## ASCII flow

```
Client/Researcher
   |
   |  (x-api-key)
   v
API Gateway (REST)  /ingest
   |
   v  (AWS_PROXY)
Lambda alex-ingest
   | \
   |  \-> SageMaker InvokeEndpoint (embeddings)
   |
   \-> S3 Vectors API (PutVectors/QueryVectors/etc.)
```

---

## How Terraform builds it (in plain terms)

1. Creates the S3 bucket and locks it down (encryption, versioning, public access block).
2. Creates an IAM role/policy for the ingest Lambda.
3. Creates the Lambda pointing at `backend/ingest/lambda_function.zip`.
4. Creates an API Gateway REST API with a single `POST /ingest` endpoint and Lambda proxy integration.
5. Adds API key + usage plan to require `x-api-key` and apply basic limits.

