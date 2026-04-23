#!/usr/bin/env python3
"""
Smoke-test that Alex AWS pieces exist (Terraform state + AWS API read-only checks).

This does **not** replace guide test scripts (e.g. backend/*/test_full.py, ingest tests).
It answers: "After terraform apply / deploy_all_aws.py, are the main resources present?"

Usage:
  cd aws && uv sync && uv run python test_all_aws.py
  cd aws && uv run python test_all_aws.py --fail-fast

Cross-checks: guides/2_sagemaker through 8_enterprise (resource presence only).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from orchestrator import (
    REPO_ROOT,
    check_tools,
    load_terraform_outputs,
    terraform_output_value,
)

TF = REPO_ROOT / "terraform"


def aws_json(cmd: list[str]) -> dict | None:
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def aws_ok(cmd: list[str]) -> bool:
    return (
        subprocess.run(cmd, capture_output=True, cwd=REPO_ROOT).returncode == 0
    )


def report(name: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"  [{tag}] {name}{extra}")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="Exit on first failure.",
    )
    args = p.parse_args()

    check_tools(require_docker=False, require_npm=False)
    print("\nAlex AWS smoke test (read-only)")
    print(f"  Repo: {REPO_ROOT}\n")

    failed = 0

    def bump(ok: bool) -> None:
        nonlocal failed
        if not ok:
            failed += 1
            if args.fail_fast:
                print("\nStopped (--fail-fast).", file=sys.stderr)
                raise SystemExit(1)

    ident = aws_json(["aws", "sts", "get-caller-identity"])
    bump(
        report(
            "AWS identity",
            ident is not None,
            ident["Arn"][:60] + "…" if ident and ident.get("Arn") else "",
        )
    )

    # --- Terraform output keys (per stack), when initialized ---
    stacks: list[tuple[str, Path, list[str], bool]] = [
        ("2_sagemaker", TF / "2_sagemaker", ["sagemaker_endpoint_name"], False),
        ("3_ingestion", TF / "3_ingestion", ["api_endpoint", "vector_bucket_name"], False),
        ("4_researcher", TF / "4_researcher", ["app_runner_service_url"], False),
        ("5_database", TF / "5_database", ["aurora_cluster_arn", "aurora_secret_arn"], False),
        ("6_agents", TF / "6_agents", ["sqs_queue_url", "lambda_functions"], False),
        ("7_frontend", TF / "7_frontend", ["cloudfront_url", "api_gateway_url"], False),
        ("8_enterprise", TF / "8_enterprise", ["dashboard_names"], True),
    ]

    for label, path, keys, optional in stacks:
        data = load_terraform_outputs(path)
        if not data:
            if optional:
                print(f"  [SKIP] Terraform {label} — not initialized (optional stack)")
            else:
                bump(report(f"Terraform {label}", False, "not initialized — deploy this stack first"))
            continue
        bump(report(f"Terraform {label}", True, "state + outputs"))
        for k in keys:
            v = terraform_output_value(data, k)
            ok = v not in (None, "", [], {})
            bump(report(f"  output {label}.{k}", ok, str(v)[:100] if ok else "missing"))

    # --- AWS API: Lambdas (Guide 6 + 7) — only if 6 / 7 stacks exist ---
    six = load_terraform_outputs(TF / "6_agents")
    seven = load_terraform_outputs(TF / "7_frontend")
    if six:
        for fn in (
            "alex-planner",
            "alex-tagger",
            "alex-reporter",
            "alex-charter",
            "alex-retirement",
        ):
            bump(
                report(
                    f"Lambda {fn}",
                    aws_ok(["aws", "lambda", "get-function", "--function-name", fn]),
                )
            )
    else:
        print("  [SKIP] Agent Lambdas — terraform/6_agents not initialized")

    if seven:
        bump(
            report(
                "Lambda alex-api",
                aws_ok(["aws", "lambda", "get-function", "--function-name", "alex-api"]),
            )
        )
    else:
        print("  [SKIP] Lambda alex-api — terraform/7_frontend not initialized")

    # --- SQS (Guide 6) ---
    if six:
        bump(
            report(
                "SQS alex-analysis-jobs",
                aws_ok(
                    [
                        "aws",
                        "sqs",
                        "get-queue-url",
                        "--queue-name",
                        "alex-analysis-jobs",
                    ]
                ),
            )
        )
    else:
        print("  [SKIP] SQS alex-analysis-jobs — terraform/6_agents not initialized")

    # --- Aurora cluster (Guide 5) ---
    db_out = load_terraform_outputs(TF / "5_database")
    if db_out:
        clusters = aws_json(
            ["aws", "rds", "describe-db-clusters", "--output", "json"]
        )
        aurora_ok = False
        detail = ""
        if clusters and "DBClusters" in clusters:
            for c in clusters["DBClusters"]:
                cid = c.get("DBClusterIdentifier", "")
                st = c.get("Status", "")
                if "alex" in cid.lower():
                    aurora_ok = st == "available"
                    detail = f"{cid} status={st}"
                    break
        bump(report("Aurora cluster (name contains 'alex')", aurora_ok, detail))
    else:
        print("  [SKIP] Aurora — terraform/5_database not initialized")

    # --- SageMaker endpoint (Guide 2) ---
    sm_out = load_terraform_outputs(TF / "2_sagemaker")
    if sm_out:
        ep = terraform_output_value(sm_out, "sagemaker_endpoint_name") or "alex-embedding-endpoint"
        sm_ok = aws_ok(
            ["aws", "sagemaker", "describe-endpoint", "--endpoint-name", str(ep)]
        )
        bump(report(f"SageMaker endpoint {ep}", sm_ok))
    else:
        print("  [SKIP] SageMaker — terraform/2_sagemaker not initialized")

    # --- CloudFront distribution (Guide 7) ---
    fe = load_terraform_outputs(TF / "7_frontend")
    cf_url = terraform_output_value(fe, "cloudfront_url") if fe else None
    cf_ok = bool(cf_url and str(cf_url).startswith("https://"))
    bump(report("Part 7 cloudfront_url in outputs", cf_ok, str(cf_url or "")[:80]))

    # --- Manual / not in Terraform ---
    print("\n  [INFO] S3 Vector bucket (Guide 3) is not verified here — confirm in S3 console.")
    print("  [INFO] For functional tests, use guides: backend/*/test_full.py, ingest tests, etc.")

    print("\n" + "=" * 72)
    if failed:
        print(f"  Finished with {failed} failure(s). Fix deploy / region / account, then re-run.")
        raise SystemExit(1)
    print("  All automated checks passed.")
    print("=" * 72)
    print("\nOpen the CloudFront URL from terraform/7_frontend output, sign in with Clerk,")
    print("then follow guides/7_frontend.md (test data, analysis, monitoring).")


if __name__ == "__main__":
    main()
