"""
Shared helpers for aws/deploy_all_aws.py and aws/destroy_all_aws.py.

See docs/6_aws-deployment.md for step order and manual (console) gaps.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess | str | None:
    """Run a command; echo it. If capture=True, return stdout (stripped) or None on failure when check=False."""
    display = " ".join(cmd)
    print(f"\n  ▶ {display}")
    if cwd:
        print(f"     (cwd: {cwd})")
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    if capture:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )
        if check and r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
        return (r.stdout or "").strip() if r.returncode == 0 else None
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return r


def sleep_gap(seconds: int, label: str) -> None:
    if seconds <= 0:
        return
    print(f"\n  … Sleep {seconds}s ({label})")
    time.sleep(seconds)


def require_tfvars(tf_dir: Path) -> None:
    tfvars = tf_dir / "terraform.tfvars"
    if not tfvars.is_file():
        print(
            f"\n❌ Missing {tfvars}\n"
            f"   Copy: cd {tf_dir} && cp terraform.tfvars.example terraform.tfvars\n"
            f"   Then edit values per guides before re-running.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def terraform_init(tf_dir: Path) -> None:
    run(["terraform", "init", "-input=false"], cwd=tf_dir)


def terraform_apply(tf_dir: Path, extra_args: list[str] | None = None) -> None:
    require_tfvars(tf_dir)
    terraform_init(tf_dir)
    cmd = ["terraform", "apply", "-input=false", "-auto-approve"]
    if extra_args:
        cmd.extend(extra_args)
    run(cmd, cwd=tf_dir)
    print_terraform_outputs(tf_dir)


def terraform_destroy(tf_dir: Path) -> None:
    if not (tf_dir / ".terraform").is_dir():
        print(f"  ⚠️  Skip destroy (not initialized): {tf_dir}")
        return
    require_tfvars(tf_dir)
    run(["terraform", "init", "-input=false"], cwd=tf_dir)
    run(
        ["terraform", "destroy", "-input=false", "-auto-approve"],
        cwd=tf_dir,
    )


def load_terraform_outputs(tf_dir: Path) -> dict | None:
    """Return parsed terraform output JSON, or None if not initialized / no output."""
    if not (tf_dir / ".terraform").is_dir():
        return None
    raw = run(
        ["terraform", "output", "-json"],
        cwd=tf_dir,
        capture=True,
        check=False,
    )
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def terraform_output_value(outputs: dict, key: str):
    ent = outputs.get(key)
    if isinstance(ent, dict) and "value" in ent:
        return ent["value"]
    return None


def print_terraform_outputs(tf_dir: Path) -> None:
    data = load_terraform_outputs(tf_dir)
    if not data:
        print("  (no terraform outputs)")
        return
    print("\n  ── Terraform outputs ──")
    for key in sorted(data.keys()):
        ent = data[key]
        val = ent.get("value", ent) if isinstance(ent, dict) else ent
        s = json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val)
        if len(s) > 500:
            s = s[:500] + "\n  … (truncated)"
        print(f"    • {key}: {s}")
    print("  ────────────────────────")


def empty_s3_bucket(bucket: str) -> None:
    print(f"\n  ▶ Emptying s3://{bucket}/")
    subprocess.run(
        ["aws", "s3", "rm", f"s3://{bucket}/", "--recursive"],
        cwd=REPO_ROOT,
        check=False,
    )


def get_terraform_raw_output(tf_dir: Path, name: str) -> str | None:
    return run(
        ["terraform", "output", "-raw", name],
        cwd=tf_dir,
        capture=True,
        check=False,
    )


def check_tools(*, require_docker: bool = True, require_npm: bool = False) -> None:
    for bin_name in ("terraform", "aws", "uv"):
        run([bin_name, "--version"], capture=True)
    ident = run(
        ["aws", "sts", "get-caller-identity"],
        capture=True,
        check=False,
    )
    if ident:
        print(f"  ▶ AWS caller: {ident}")
    if require_npm:
        run(["npm", "--version"], capture=True)
    if require_docker:
        run(["docker", "info"], capture=True)
