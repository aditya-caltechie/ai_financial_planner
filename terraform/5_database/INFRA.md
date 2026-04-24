## `terraform/5_database` — Aurora Serverless v2 (PostgreSQL) + Data API

This stack provisions the **Aurora Serverless v2** PostgreSQL cluster used by the API and agents (Guide 5). It enables the **RDS Data API** so Lambdas and local scripts can talk to the database without VPC networking complexity.

---

## What this stack creates

| AWS service | Resource(s) | Purpose |
| --- | --- | --- |
| Secrets Manager | `alex-aurora-credentials-<random>` + secret version | Stores DB username/password. Name includes a random suffix. |
| VPC (default) | reads default VPC + subnets | Uses your default VPC for subnet selection. |
| RDS / Aurora | `alex-aurora-cluster` (Aurora PostgreSQL) | Serverless v2 cluster with Data API enabled. |
| RDS / Aurora | `alex-aurora-instance-1` | Serverless instance for the cluster. |
| Security Group | `alex-aurora-sg` | Allows Postgres within the VPC CIDR. |
| DB subnet group | `alex-aurora-subnet-group` | Uses default subnets. |
| IAM | `alex-lambda-aurora-role` + policies | Convenience role/policy granting Data API + secret read + logs. (Other stacks also create their own roles.) |

---

## Key inputs

| Variable | Meaning |
| --- | --- |
| `aws_region` | Region to deploy. |
| `min_capacity` / `max_capacity` | Aurora Serverless v2 ACU scaling bounds (cost control). |

---

## Outputs you’ll use later

| Output | Used by | Why |
| --- | --- | --- |
| `aurora_cluster_arn` | `.env`, `terraform/6_agents`, `terraform/7_frontend` | Required for Data API calls. |
| `aurora_secret_arn` | `.env`, `terraform/6_agents`, `terraform/7_frontend` | Used to fetch DB credentials. |
| `database_name` | `.env` / API & agents | DB name (default `alex`). |

---

## ASCII flow

```
Secrets Manager (username/password)
          |
          v
Aurora Serverless v2 cluster (Data API enabled)
          ^
          |
   Lambda / API / agents use:
     rds-data:ExecuteStatement
     secretsmanager:GetSecretValue
```

---

## How Terraform builds it (in plain terms)

1. Generates a random password and creates a Secrets Manager secret/version.
2. Looks up the default VPC and its subnets; creates a subnet group and security group.
3. Creates the Aurora cluster (engine `aurora-postgresql`, serverless v2 scaling, Data API enabled).
4. Creates a serverless instance attached to the cluster.
5. Creates an IAM role/policy that can call the Data API and read the secret (helpful reference for Lambda permissions).

