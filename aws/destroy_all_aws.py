#!/usr/bin/env python3
"""
Tear down Alex AWS resources created by Terraform (reverse of docs/6_aws-deployment.md).

Does NOT delete:
  - S3 Vector buckets (console) — prints reminder at the end
  - App Runner (terraform/4_researcher) by default — the Researcher service is **paused**, not deleted;
    `terraform destroy` for that stack is skipped unless you pass **--destroy-researcher-terraform**.

Part 7 S3 bucket is emptied before destroy (same idea as scripts/destroy.py).

Uses the same AWS credential chain as `terraform` / `aws` (root or IAM); does not depend on Guide 1.

Usage:
  cd aws && uv run python destroy_all_aws.py --yes
  cd aws && uv run python destroy_all_aws.py --yes --sleep 10
  cd aws && uv run python destroy_all_aws.py --from-stack enterprise --to-stack sagemaker
  cd aws && uv run python destroy_all_aws.py --yes --destroy-researcher-terraform   # also destroy 4_researcher via Terraform
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
    empty_s3_bucket,
    get_terraform_raw_output,
    print_terraform_outputs,
    sleep_gap,
    terraform_destroy,
)

TF_ROOT = REPO_ROOT / "terraform"

APP_RUNNER_DESTROY_NOTICE = """
================================================================================
AWS APP RUNNER — RESEARCHER (terraform/4_researcher): NOT DELETED BY THIS RUN
================================================================================
THIS STEP DOES NOT RUN `terraform destroy` ON THE RESEARCHER STACK BY DEFAULT.
THE APP RUNNER SERVICE IS LEFT IN AWS SO YOU CAN RESUME OR MANAGE IT IN CONSOLE.

WHEN POSSIBLE, THIS SCRIPT CALLS:  aws apprunner pause-service
(PAUSE STOPS INSTANCE COMPUTE FOR THE SERVICE; YOU MAY STILL SEE SMALL METADATA COSTS.)

APP RUNNER CANNOT (RE)DEPLOY AFTER APRIL 30TH — PLAN AHEAD. IF `pause-service` FAILS
HERE (CLI ERROR, WRONG REGION, MISSING PERMISSIONS), PAUSE THE SERVICE MANUALLY IN
THE AWS CONSOLE BEFORE THAT DATE.

TO FULLY DESTROY THE RESEARCHER STACK (INCLUDING APP RUNNER + ECR + SCHEDULER), RUN:
  destroy_all_aws.py --yes --destroy-researcher-terraform
================================================================================
"""

# Destroy order: dependent / expensive stacks first (see docs/6_aws-deployment.md).
DESTROY_SEQUENCE: list[tuple[str, Path]] = [
    ("8_enterprise", TF_ROOT / "8_enterprise"),
    ("7_frontend", TF_ROOT / "7_frontend"),
    ("6_agents", TF_ROOT / "6_agents"),
    ("5_database", TF_ROOT / "5_database"),
    ("4_researcher", TF_ROOT / "4_researcher"),
    ("3_ingestion", TF_ROOT / "3_ingestion"),
    ("2_sagemaker", TF_ROOT / "2_sagemaker"),
]


def _banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def empty_frontend_bucket_if_possible() -> None:
    d = TF_ROOT / "7_frontend"
    if not (d / ".terraform").is_dir():
        print("  ⚠️  7_frontend not initialized — skip S3 empty")
        return
    bucket = get_terraform_raw_output(d, "s3_bucket_name")
    if bucket:
        print(f"\n  📦 Frontend bucket (from terraform output): {bucket}")
        empty_s3_bucket(bucket)
    else:
        print("  ⚠️  Could not read s3_bucket_name output; skip pre-empty")


def _resolve_apprunner_service_arn(tf_dir: Path) -> str | None:
    """Service ARN from Terraform output, or by listing App Runner services (name alex-researcher)."""
    if (tf_dir / ".terraform").is_dir() and (tf_dir / "terraform.tfvars").is_file():
        raw = get_terraform_raw_output(tf_dir, "app_runner_service_id")
        if raw:
            s = raw.strip()
            if s.startswith("arn:aws:apprunner:"):
                return s
            if "Not created" in s:
                return None
    r = subprocess.run(
        ["aws", "apprunner", "list-services", "--output", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    for svc in data.get("ServiceSummaryList", []) or []:
        if str(svc.get("ServiceName", "")) == "alex-researcher":
            arn = svc.get("ServiceArn")
            return str(arn) if arn else None
    return None


def pause_researcher_apprunner(tf_dir: Path) -> None:
    print(APP_RUNNER_DESTROY_NOTICE)
    arn = _resolve_apprunner_service_arn(tf_dir)
    if not arn:
        print("  ⚠️  Could not resolve App Runner service ARN (no Terraform output / list-services empty).")
        print("  ⚠️  PAUSE THE alex-researcher SERVICE MANUALLY IN THE AWS CONSOLE IF IT STILL EXISTS.")
        return
    print(f"\n  ▶ aws apprunner pause-service --service-arn {arn}")
    pr = subprocess.run(
        ["aws", "apprunner", "pause-service", "--service-arn", arn],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if pr.returncode == 0:
        print("  ✅ pause-service request accepted (App Runner pauses asynchronously).")
    else:
        err = (pr.stderr or pr.stdout or "").strip()
        print(f"  ⚠️  pause-service failed (exit {pr.returncode}): {err[:500]}")
        print("  ⚠️  PAUSE THE SERVICE MANUALLY IN THE AWS CONSOLE BEFORE APRIL 30TH IF YOU NEED IT PAUSED.")


def destroy_stack(name: str, tf_dir: Path, *, destroy_researcher_terraform: bool) -> None:
    _banner(f"DESTROY — {name} ({tf_dir.relative_to(REPO_ROOT)})")
    if name == "7_frontend":
        empty_frontend_bucket_if_possible()
    if name == "4_researcher" and not destroy_researcher_terraform:
        # Keep App Runner + Terraform state; pause service only (best-effort).
        if not (tf_dir / "terraform.tfvars").is_file():
            print(f"  ⚠️  No terraform.tfvars — cannot read outputs; still try pause via list-services")
        if (tf_dir / ".terraform").is_dir():
            try:
                print_terraform_outputs(tf_dir)
            except Exception as e:
                print(f"  ⚠️  Could not print outputs: {e}")
        pause_researcher_apprunner(tf_dir)
        print("\n  ⏭️  Skipping `terraform destroy` for 4_researcher (App Runner preserved).")
        print("  ⏭️  Use --destroy-researcher-terraform to destroy this stack including App Runner.")
        print(f"  ✅ Finished pause/skip for {name}")
        return
    if not (tf_dir / "terraform.tfvars").is_file():
        print(f"  ⚠️  No terraform.tfvars — skip {name}")
        return
    if not (tf_dir / ".terraform").is_dir():
        print(f"  ⚠️  Not initialized — skip {name}")
        return
    try:
        print_terraform_outputs(tf_dir)
    except Exception as e:
        print(f"  ⚠️  Could not print outputs: {e}")
    terraform_destroy(tf_dir)
    print(f"  ✅ Finished destroy for {name}")


def parse_args() -> argparse.Namespace:
    ids = [x[0] for x in DESTROY_SEQUENCE]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--yes", action="store_true", help="Required: confirm you intend to destroy AWS resources.")
    p.add_argument(
        "--from-stack",
        default="8_enterprise",
        choices=ids,
        help="First stack id in destroy order (default: 8_enterprise).",
    )
    p.add_argument(
        "--to-stack",
        default="2_sagemaker",
        choices=ids,
        help="Last stack id in destroy order (default: 2_sagemaker).",
    )
    p.add_argument(
        "--sleep",
        type=int,
        default=5,
        metavar="SEC",
        help="Sleep between destroys (default: 5). Use 0 to disable.",
    )
    p.add_argument("--dry-run", action="store_true", help="List stacks that would be destroyed, then exit.")
    p.add_argument(
        "--destroy-researcher-terraform",
        action="store_true",
        help=(
            "Also run `terraform destroy` in terraform/4_researcher (deletes App Runner, ECR, scheduler). "
            "Default: skip destroy there and only pause App Runner."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.dry_run:
        order = [x[0] for x in DESTROY_SEQUENCE]
        i0, i1 = order.index(args.from_stack), order.index(args.to_stack)
        if i0 > i1:
            print("--from-stack must be earlier in teardown order than --to-stack", file=sys.stderr)
            raise SystemExit(2)
        segment = DESTROY_SEQUENCE[i0 : i1 + 1]
        print("Dry run — would process stacks:", " → ".join(n for n, _ in segment))
        if any(n == "4_researcher" for n, _ in segment) and not args.destroy_researcher_terraform:
            print(
                "  Note: 4_researcher — would PAUSE App Runner and SKIP terraform destroy "
                "(use --destroy-researcher-terraform to include full destroy)."
            )
        raise SystemExit(0)

    if not args.yes:
        print("Refusing to run without --yes (this destroys AWS resources).", file=sys.stderr)
        raise SystemExit(2)

    order = [x[0] for x in DESTROY_SEQUENCE]
    i0, i1 = order.index(args.from_stack), order.index(args.to_stack)
    if i0 > i1:
        print("--from-stack must be earlier in teardown order than --to-stack", file=sys.stderr)
        raise SystemExit(2)
    segment = DESTROY_SEQUENCE[i0 : i1 + 1]

    check_tools(require_docker=False, require_npm=False)
    print("\nAlex full destroy orchestrator")
    print(f"  Repo: {REPO_ROOT}")
    print(f"  Stacks: {' → '.join(n for n, _ in segment)}")
    if any(n == "4_researcher" for n, _ in segment) and not args.destroy_researcher_terraform:
        print(
            "  Note: 4_researcher — App Runner will be PAUSED (not deleted); "
            "terraform destroy skipped unless --destroy-researcher-terraform."
        )

    for name, path in segment:
        destroy_stack(name, path, destroy_researcher_terraform=args.destroy_researcher_terraform)
        sleep_gap(args.sleep, f"after {name}")

    print("\n" + "=" * 72)
    print("  Terraform teardown finished.")
    print("=" * 72)
    print("\nManual cleanup (not done by this script):")
    print("  • S3 Vector buckets + indexes — AWS Console (Guide 3)")
    print("  • Clerk / OpenAI keys — rotate or delete in vendor dashboards if desired")
    if not args.destroy_researcher_terraform and any(n == "4_researcher" for n, _ in segment):
        print("  • App Runner `alex-researcher` — left in AWS (paused when possible); Terraform stack 4_researcher not destroyed")
        print("    To remove it later: `cd aws && uv run python destroy_all_aws.py --yes --from-stack 4_researcher --to-stack 4_researcher --destroy-researcher-terraform`")
    print("\nValidate teardown (read-only):")
    print("  cd aws && uv run python validate_destroy_aws.py")


if __name__ == "__main__":
    main()
