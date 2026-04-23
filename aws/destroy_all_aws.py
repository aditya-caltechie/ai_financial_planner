#!/usr/bin/env python3
"""
Tear down Alex AWS resources created by Terraform (reverse of docs/6_aws-deployment.md).

Does NOT delete:
  - S3 Vector buckets (console) — prints reminder at the end

Part 7 S3 bucket is emptied before destroy (same idea as scripts/destroy.py).

Usage:
  cd aws && uv run python destroy_all_aws.py --yes
  cd aws && uv run python destroy_all_aws.py --yes --sleep 10
  cd aws && uv run python destroy_all_aws.py --from-stack enterprise --to-stack sagemaker
"""

from __future__ import annotations

import argparse
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


def destroy_stack(name: str, tf_dir: Path) -> None:
    _banner(f"DESTROY — {name} ({tf_dir.relative_to(REPO_ROOT)})")
    if name == "7_frontend":
        empty_frontend_bucket_if_possible()
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
        print("Dry run — would destroy:", " → ".join(n for n, _ in segment))
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

    for name, path in segment:
        destroy_stack(name, path)
        sleep_gap(args.sleep, f"after {name}")

    print("\n" + "=" * 72)
    print("  Terraform teardown finished.")
    print("=" * 72)
    print("\nManual cleanup (not done by this script):")
    print("  • S3 Vector buckets + indexes — AWS Console (Guide 3)")
    print("  • Clerk / OpenAI keys — rotate or delete in vendor dashboards if desired")


if __name__ == "__main__":
    main()
