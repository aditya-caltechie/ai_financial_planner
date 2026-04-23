#!/usr/bin/env python3
"""
Post-teardown checks: confirm **Alex Terraform-managed** resources are gone in AWS
(read-only `aws` CLI). Use after `destroy_all_aws.py --yes` to reduce surprise billing.

This is the **inverse** of `validate_deploy_aws.py` (which checks resources **exist** after deploy).

What is **not** checked (manual / outside Terraform destroy):
  • S3 **Vector** buckets and indexes (Guide 3 — console only; same note as destroy script)
  • Third-party keys (OpenAI, Clerk, Polygon) — vendor dashboards
  • Leftover **IAM** roles from failed applies (usually no hourly cost; list in IAM console if unsure)
  • Resources in **other** AWS regions (this script uses your CLI default region unless --region)

Exit code **0** = every check saw no Alex resource (or API could not contradict teardown).
Exit code **1** = at least one check found a resource that still exists (--fail-fast stops at first).

Usage:
  cd aws && uv run python validate_destroy_aws.py
  cd aws && uv run python validate_destroy_aws.py --fail-fast
  cd aws && uv run python validate_destroy_aws.py --region us-west-2
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from orchestrator import REPO_ROOT, check_tools

TF = REPO_ROOT / "terraform"


def _env(region: str | None) -> dict[str, str]:
    e = os.environ.copy()
    if region:
        e["AWS_DEFAULT_REGION"] = region
        e["AWS_REGION"] = region
    return e


def aws_json(cmd: list[str], *, region: str | None) -> dict | None:
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=_env(region),
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def aws_rc(cmd: list[str], *, region: str | None) -> int:
    return subprocess.run(cmd, capture_output=True, cwd=REPO_ROOT, env=_env(region)).returncode


def report(name: str, ok: bool, detail: str = "") -> bool:
    tag = "OK" if ok else "STILL_PRESENT"
    extra = f" — {detail}" if detail else ""
    print(f"  [{tag}] {name}{extra}")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="Exit on first resource that still exists.",
    )
    p.add_argument(
        "--region",
        metavar="NAME",
        default=None,
        help="AWS region for all CLI calls (default: profile/env AWS_REGION).",
    )
    args = p.parse_args()
    region = args.region

    check_tools(require_docker=False, require_npm=False)
    print("\nAlex validate-destroy (read-only, expect resources **absent**)")
    print(f"  Repo: {REPO_ROOT}\n")

    ident = aws_json(["aws", "sts", "get-caller-identity"], region=region)
    if not ident:
        print("  [FATAL] aws sts get-caller-identity failed — fix credentials / region.", file=sys.stderr)
        raise SystemExit(2)
    acct = ident.get("Account", "")
    arn = ident.get("Arn", "")
    print(f"  Account: {acct}  Caller: {arn[:72]}…\n")

    failed = 0
    skipped = 0

    def bump(ok: bool) -> None:
        nonlocal failed
        if not ok:
            failed += 1
            if args.fail_fast:
                print("\nStopped (--fail-fast): something still exists in AWS.", file=sys.stderr)
                raise SystemExit(1)

    def skip(msg: str) -> None:
        nonlocal skipped
        skipped += 1
        print(f"  [SKIP] {msg}")

    # --- Lambda (Parts 3, 4, 6, 7) ---
    lambdas = (
        "alex-api",
        "alex-ingest",
        "alex-planner",
        "alex-tagger",
        "alex-reporter",
        "alex-charter",
        "alex-retirement",
        "alex-researcher-scheduler",
    )
    for fn in lambdas:
        rc = aws_rc(["aws", "lambda", "get-function", "--function-name", fn], region=region)
        bump(report(f"Lambda absent: {fn}", rc != 0, "found" if rc == 0 else "not found"))

    # --- SQS (Part 6) ---
    for q in ("alex-analysis-jobs", "alex-analysis-jobs-dlq"):
        rc = aws_rc(["aws", "sqs", "get-queue-url", "--queue-name", q], region=region)
        bump(report(f"SQS absent: {q}", rc != 0, "queue URL resolved" if rc == 0 else "no queue"))

    # --- Aurora (Part 5) ---
    clusters = aws_json(["aws", "rds", "describe-db-clusters", "--output", "json"], region=region)
    if clusters is None:
        skip("RDS describe-db-clusters failed — verify Aurora in console")
    else:
        detail = ""
        aurora_ok = True
        for c in clusters.get("DBClusters", []):
            cid = str(c.get("DBClusterIdentifier", ""))
            if "alex-aurora" in cid.lower():
                aurora_ok = False
                detail = f"{cid} status={c.get('Status', '')}"
                break
        bump(report("RDS: no alex-aurora cluster", aurora_ok, detail))

    # --- SageMaker endpoint (Part 2) ---
    rc = aws_rc(
        ["aws", "sagemaker", "describe-endpoint", "--endpoint-name", "alex-embedding-endpoint"],
        region=region,
    )
    bump(
        report(
            "SageMaker endpoint absent: alex-embedding-endpoint",
            rc != 0,
            "endpoint exists" if rc == 0 else "not found",
        )
    )

    # --- S3 buckets (Parts 3, 6, 7 naming convention) ---
    if acct:
        for bucket in (
            f"alex-frontend-{acct}",
            f"alex-lambda-packages-{acct}",
            f"alex-vectors-{acct}",
        ):
            rc = aws_rc(["aws", "s3api", "head-bucket", "--bucket", bucket], region=region)
            bump(report(f"S3 bucket absent: {bucket}", rc != 0, "exists" if rc == 0 else "not found"))

    # --- ECR (Part 4) ---
    rc = aws_rc(
        ["aws", "ecr", "describe-repositories", "--repository-names", "alex-researcher"],
        region=region,
    )
    bump(report("ECR repo absent: alex-researcher", rc != 0, "exists" if rc == 0 else "not found"))

    # --- App Runner (Part 4) ---
    svc = aws_json(["aws", "apprunner", "list-services", "--output", "json"], region=region)
    if svc is None:
        skip("App Runner list-services failed — verify App Runner console")
    else:
        ar_detail = ""
        apprunner_ok = True
        for s in svc.get("ServiceSummaryList", []):
            name = str(s.get("ServiceName", ""))
            if name == "alex-researcher":
                apprunner_ok = False
                ar_detail = str(s.get("Status", ""))
                break
        bump(report("App Runner absent: alex-researcher", apprunner_ok, ar_detail))

    # --- HTTP API Gateway name from Part 7 ---
    apis = aws_json(["aws", "apigatewayv2", "get-apis", "--output", "json"], region=region)
    if apis is None:
        skip("API Gateway get-apis failed — verify HTTP APIs in console")
    else:
        api_detail = ""
        api_ok = True
        for item in apis.get("Items", []):
            if item.get("Name") == "alex-api-gateway":
                api_ok = False
                api_detail = str(item.get("ApiId", ""))
                break
        bump(report("API Gateway v2 absent: alex-api-gateway", api_ok, api_detail))

    # --- CloudFront: comment from Part 7 main.tf ---
    cf = aws_json(["aws", "cloudfront", "list-distributions", "--output", "json"], region=region)
    if cf is None:
        skip("CloudFront list-distributions failed — verify distributions in console")
    else:
        cf_detail = ""
        cf_ok = True
        items = cf.get("DistributionList", {}).get("Items", []) or []
        for d in items:
            if d.get("Comment") == "Alex Financial Advisor Frontend":
                cf_ok = False
                cf_detail = str(d.get("Id", ""))
                break
        bump(report("CloudFront absent (Alex comment)", cf_ok, cf_detail))

    # --- EventBridge rule (Part 4 optional) ---
    rc = aws_rc(["aws", "events", "describe-rule", "--name", "alex-research-schedule"], region=region)
    bump(report("EventBridge rule absent: alex-research-schedule", rc != 0, "exists" if rc == 0 else "not found"))

    # --- CloudWatch dashboards (Part 8) ---
    dash = aws_json(["aws", "cloudwatch", "list-dashboards", "--output", "json"], region=region)
    if dash is None:
        skip("CloudWatch list-dashboards failed — verify dashboards in console")
    else:
        alex_dashes: list[str] = []
        for e in dash.get("DashboardEntries", []) or []:
            name = str(e.get("DashboardName", ""))
            if name.startswith("alex-"):
                alex_dashes.append(name)
        bump(
            report(
                "CloudWatch dashboards: no alex-* names",
                len(alex_dashes) == 0,
                ", ".join(alex_dashes) if alex_dashes else "none",
            )
        )

    # --- Terraform local state: optional hint ---
    print("\n  --- Local Terraform (informational) ---")
    for label, rel in (
        ("2_sagemaker", "2_sagemaker"),
        ("3_ingestion", "3_ingestion"),
        ("4_researcher", "4_researcher"),
        ("5_database", "5_database"),
        ("6_agents", "6_agents"),
        ("7_frontend", "7_frontend"),
        ("8_enterprise", "8_enterprise"),
    ):
        d = TF / rel
        st = d / "terraform.tfstate"
        if not st.is_file():
            print(f"  [INFO] {label}: no terraform.tfstate file")
            continue
        try:
            raw = st.read_text(encoding="utf-8")
            data = json.loads(raw)
            n = len(data.get("resources", []) or [])
            if n == 0:
                print(f"  [INFO] {label}: state file exists, 0 resources (typical after destroy)")
            else:
                print(f"  [WARN] {label}: terraform.tfstate still lists {n} resource(s) — run terraform state list")
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [INFO] {label}: could not read state ({e})")

    print("\n" + "=" * 72)
    print("  Manual / not verified by CLI defaults:")
    print("    • S3 **Vector** buckets (S3 console → Vector buckets) — still billed if left behind")
    print("    • Other regions — re-run with --region if you deployed outside default")
    print("=" * 72)

    if failed:
        print(f"\n  Result: {failed} check(s) found resources still in AWS. Review STILL_PRESENT lines above.")
        raise SystemExit(1)
    if skipped:
        print(f"\n  Result: no resources detected by checks that ran; {skipped} check(s) skipped (API errors).")
        print("  Fix CLI permissions or verify those services in the console, then re-run.")
        raise SystemExit(0)
    print("\n  Result: no matching Alex resources found by these checks.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
