#!/usr/bin/env python3
"""
Full Alex AWS deploy orchestration (Terraform stacks + uv commands).

Matches docs/6_aws-deployment.md.

S3 **Vector** bucket + index are still created in the **AWS Console** (Guide 3); this script pauses there unless you pass **--skip-vectors-prompt** after the bucket already exists.

Part 7 UI/API is delegated to scripts/deploy.py (same as the course).

Uses whatever AWS credentials the CLI has (IAM user, SSO, assumed role, or root); no separate course IAM user is required by this script.

Usage (from repo root):
  cd aws && uv sync && uv run python deploy_all_aws.py --help
  cd aws && uv run python deploy_all_aws.py --sleep 20
  cd aws && uv run python deploy_all_aws.py --from-step sagemaker --to-step agents
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

from orchestrator import (
    REPO_ROOT,
    check_tools,
    load_terraform_outputs,
    run,
    sleep_gap,
    terraform_apply,
    terraform_output_value,
)

SCRIPTS = REPO_ROOT / "scripts"
TF = REPO_ROOT / "terraform"

DEPLOY_STEP_PLAN: dict[str, str] = {
    "sagemaker": "Terraform (2_sagemaker): SageMaker embedding endpoint + role",
    "vectors": "Manual (console): S3 Vector bucket + index (Guide 3)",
    "ingest": "Package ingest + Terraform (3_ingestion): ingest Lambda + API Gateway + API key",
    "researcher-partial": "Terraform (4_researcher target): ECR repo + App Runner IAM role",
    "researcher-image": "Docker build/push: Researcher image → ECR",
    "researcher-full": "Terraform (4_researcher): App Runner service + optional schedule",
    "database": "Terraform (5_database): Aurora Serverless v2 + secret",
    "db-migrate": "uv run (backend/database): test Data API + migrations + seed data",
    "agents": "Package agents + Terraform (6_agents): SQS + 5 Lambdas + lambda-packages bucket",
    "part7": "scripts/deploy.py (Guide 7): API Lambda + API Gateway + S3/CloudFront + upload/invalidate",
    "enterprise": "Terraform (8_enterprise): CloudWatch dashboards/alarms",
}


def _fmt_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    return f"{int(s // 60)}m{int(s % 60):02d}s"


def _get_database_env_from_tf() -> dict[str, str]:
    """Prefer fresh TF outputs over stale .env when running db migration scripts."""
    out = load_terraform_outputs(TF / "5_database") or {}
    cluster = terraform_output_value(out, "aurora_cluster_arn")
    secret = terraform_output_value(out, "aurora_secret_arn")
    dbname = terraform_output_value(out, "database_name")
    env: dict[str, str] = {}
    if cluster:
        env["AURORA_CLUSTER_ARN"] = str(cluster)
    if secret:
        env["AURORA_SECRET_ARN"] = str(secret)
    if dbname:
        env["AURORA_DATABASE"] = str(dbname)
    # Some scripts fall back to DEFAULT_AWS_REGION; keep it aligned with stack vars.
    env["DEFAULT_AWS_REGION"] = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    return env


def print_post_deploy_expectations(ran_part7: bool) -> None:
    """After a full run, tell the user what URLs to open (Guide 7)."""
    out = load_terraform_outputs(TF / "7_frontend")
    print("\n" + "=" * 72)
    print("  When deploy is complete — what to expect (Guide 7)")
    print("=" * 72)
    if not ran_part7 or not out:
        print("  Part 7 (`part7` step or `cd scripts && uv run deploy.py`) was not in this run,")
        print("  or `terraform/7_frontend` has no state yet.")
        print("  After you deploy Part 7, Terraform prints:")
        print("    • cloudfront_url — public Alex UI (HTTPS)")
        print("    • api_gateway_url — backend used by the browser as /api/* via CloudFront")
        print("  You sign in with Clerk, then use Accounts / Advisor Team per the guide.")
        return
    cf = terraform_output_value(out, "cloudfront_url")
    api = terraform_output_value(out, "api_gateway_url")
    bucket = terraform_output_value(out, "s3_bucket_name")
    print(f"  • Open the Alex UI: {cf}")
    print(f"  • API origin (proxied as /api/*): {api}")
    print(f"  • Static files bucket: {bucket}")
    print("  • Wait up to ~10–15 minutes if CloudFront was just created (edge propagation).")
    print("  • Clerk: use the app you configured; first visit may redirect to sign-in.")
    print("  • Deep guide: guides/7_frontend.md — populate test data, run analysis, CloudWatch.")
    print("  • Optional validate: `cd aws && uv run python validate_deploy_aws.py`")


def _step_banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def step_sagemaker() -> None:
    _step_banner("STEP 2 — SageMaker embeddings (terraform/2_sagemaker)")
    terraform_apply(REPO_ROOT / "terraform" / "2_sagemaker")


def step_vectors_console() -> None:
    _step_banner("STEP 3 — S3 Vectors bucket + index (AWS Console)")
    print("  Terraform cannot create S3 *Vector* buckets; do this in the console (Guide 3):")
    print(f"    {REPO_ROOT / 'guides' / '3_ingest.md'}")
    print("  Put VECTOR_BUCKET / index name into .env and terraform/6_agents/terraform.tfvars as the guides show.")
    print("  Use --skip-vectors-prompt if the bucket + index already exist and you do not want this pause.")
    input("  [Enter when vector bucket + index exist] ")


def step_ingest() -> None:
    _step_banner("STEP 4 — Ingest Lambda + API (package + terraform/3_ingestion)")
    run(["uv", "run", "package.py"], cwd=REPO_ROOT / "backend" / "ingest")
    terraform_apply(REPO_ROOT / "terraform" / "3_ingestion")


def step_researcher_partial() -> None:
    _step_banner("STEP 5a — Researcher ECR + IAM (terraform/4_researcher partial apply)")
    d = REPO_ROOT / "terraform" / "4_researcher"
    terraform_apply(
        d,
        extra_args=[
            "-target=aws_ecr_repository.researcher",
            "-target=aws_iam_role.app_runner_role",
        ],
    )


def step_researcher_image() -> None:
    _step_banner("STEP 5b — Researcher Docker image → ECR (backend/researcher)")
    print("  Ensure backend/researcher/server.py REGION + MODEL match Bedrock access.")
    run(["uv", "run", "deploy.py"], cwd=REPO_ROOT / "backend" / "researcher")


def step_researcher_full() -> None:
    _step_banner("STEP 5c — Researcher App Runner + optional schedule (terraform/4_researcher)")
    terraform_apply(REPO_ROOT / "terraform" / "4_researcher")


def step_database() -> None:
    _step_banner("STEP 6 — Aurora (terraform/5_database)")
    terraform_apply(REPO_ROOT / "terraform" / "5_database")


def step_db_migrate() -> None:
    _step_banner("STEP 7 — Database schema + seed (backend/database)")
    db = REPO_ROOT / "backend" / "database"
    # Use fresh outputs from terraform/5_database when available (secret names are random-suffixed),
    # so we don't fail due to stale .env values after re-deploys.
    env = _get_database_env_from_tf()
    run(["uv", "run", "test_data_api.py"], cwd=db, env_overrides=env)
    run(["uv", "run", "run_migrations.py"], cwd=db, env_overrides=env)
    run(["uv", "run", "seed_data.py"], cwd=db, env_overrides=env)


def step_agents() -> None:
    _step_banner("STEP 8 — Agent Lambdas + SQS (package + terraform/6_agents)")
    run(["uv", "run", "package_docker.py"], cwd=REPO_ROOT / "backend")
    terraform_apply(REPO_ROOT / "terraform" / "6_agents")


def step_agents_refresh() -> None:
    _step_banner("STEP 8b (optional) — Re-sync agent Lambda artifacts (deploy_all_lambdas.py)")
    run(["uv", "run", "deploy_all_lambdas.py"], cwd=REPO_ROOT / "backend")


def step_part7_via_course_script() -> None:
    _step_banner("STEP 9 — Frontend + API (scripts/deploy.py = Guide 7)")
    print("  Uses Docker, Terraform 7_frontend, npm build, S3 upload, CloudFront invalidation.")
    if not SCRIPTS.is_dir():
        print(f"❌ Missing {SCRIPTS}", file=sys.stderr)
        raise SystemExit(1)
    run(["uv", "run", "deploy.py"], cwd=SCRIPTS)


def step_enterprise() -> None:
    _step_banner("STEP 10 (optional) — Enterprise dashboards (terraform/8_enterprise)")
    terraform_apply(REPO_ROOT / "terraform" / "8_enterprise")


# Ordered registry: id -> callable (aligns with docs/6_aws-deployment.md after Guide 2)
DEPLOY_SEQUENCE: list[tuple[str, callable]] = [
    ("sagemaker", step_sagemaker),
    ("vectors", step_vectors_console),
    ("ingest", step_ingest),
    ("researcher-partial", step_researcher_partial),
    ("researcher-image", step_researcher_image),
    ("researcher-full", step_researcher_full),
    ("database", step_database),
    ("db-migrate", step_db_migrate),
    ("agents", step_agents),
    ("part7", step_part7_via_course_script),
    ("enterprise", step_enterprise),
]


def parse_args() -> argparse.Namespace:
    ids = [x[0] for x in DEPLOY_SEQUENCE]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--from-step",
        default="sagemaker",
        choices=ids,
        help="First deploy step id (default: sagemaker). Use e.g. ingest if SageMaker + vectors are already done.",
    )
    p.add_argument(
        "--to-step",
        default="enterprise",
        choices=ids,
        help="Last deploy step id to run (default: enterprise).",
    )
    p.add_argument(
        "--sleep",
        type=int,
        default=15,
        metavar="SEC",
        help="Seconds to sleep after each Terraform apply (default: 15). Use 0 to disable.",
    )
    p.add_argument(
        "--skip-vectors-prompt",
        action="store_true",
        help=(
            "Skip the Enter-key pause for Guide 3 (S3 Vector bucket + index already created in the console)."
        ),
    )
    p.add_argument(
        "--run-8b",
        action="store_true",
        help="After 'agents', run deploy_all_lambdas.py (Terraform taint/apply in 6_agents).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which steps would run, then exit.",
    )
    return p.parse_args()


def main() -> None:
    started_wall = datetime.now(timezone.utc)
    started = time.perf_counter()
    args = parse_args()
    ids = [x[0] for x in DEPLOY_SEQUENCE]
    i0 = ids.index(args.from_step)
    i1 = ids.index(args.to_step)
    if i0 > i1:
        print("--from-step must not be after --to-step", file=sys.stderr)
        raise SystemExit(2)

    slice_steps = DEPLOY_SEQUENCE[i0 : i1 + 1]
    if args.dry_run:
        print("Dry run — would execute:", ", ".join(s[0] for s in slice_steps))
        if args.run_8b and any(s[0] == "agents" for s in slice_steps):
            print("  + step 8b deploy_all_lambdas.py after agents")
        raise SystemExit(0)

    need_docker = any(s[0] in ("researcher-image", "agents", "part7") for s in slice_steps)
    need_npm = any(s[0] == "part7" for s in slice_steps)
    check_tools(require_docker=need_docker, require_npm=need_npm)
    print("\nAlex full deploy orchestrator")
    print(f"  Repo: {REPO_ROOT}")
    print(f"  Steps: {' → '.join(s[0] for s in slice_steps)}")
    print(f"  Post-apply sleep: {args.sleep}s")
    print(f"  Started: {started_wall.isoformat()}")
    print("\nPlan (what this run will deploy):")
    for sid, _ in slice_steps:
        desc = DEPLOY_STEP_PLAN.get(sid, "")
        print(f"  • {sid}: {desc}")

    ran_part7 = False
    step_times: list[tuple[str, float]] = []
    for sid, fn in slice_steps:
        t0 = time.perf_counter()
        if sid == "vectors" and args.skip_vectors_prompt:
            print("\n  … Skipping S3 Vectors console confirmation (--skip-vectors-prompt)")
            continue
        fn()
        dt = time.perf_counter() - t0
        step_times.append((sid, dt))
        print(f"\n  ⏱️  Step '{sid}' duration: {_fmt_seconds(dt)}")
        if sid == "part7":
            ran_part7 = True
        if sid not in ("vectors", "db-migrate"):
            sleep_gap(args.sleep, f"after {sid}")

        if sid == "agents" and args.run_8b:
            step_agents_refresh()
            sleep_gap(args.sleep, "after agents refresh")

    print("\n" + "=" * 72)
    print("  Deploy sequence finished.")
    print("=" * 72)
    total = time.perf_counter() - started
    ended_wall = datetime.now(timezone.utc)
    print(f"\nStarted: {started_wall.isoformat()}")
    print(f"Ended:   {ended_wall.isoformat()}")
    print(f"Total:   {_fmt_seconds(total)}")
    if step_times:
        print("\nPer-step timing:")
        for sid, dt in step_times:
            print(f"  • {sid}: {_fmt_seconds(dt)}")
    print("\nNext: sync `.env` from `terraform output` in each stack if guides require it,")
    print("then run deploy validation:")
    print("  cd aws && uv run python validate_deploy_aws.py")
    print_post_deploy_expectations(ran_part7)


if __name__ == "__main__":
    main()
