#!/usr/bin/env python3
"""Keep lineage-assets' per-QR manifests + index in sync with the sheets.

A cron-friendly daemon that, inside a working clone of TrueSightDAO/lineage-assets:

  1. fast-forwards the clone to origin/main,
  2. runs scripts/seed_from_sheet.py --execute  (rebuilds qrs/*.json from the
     Agroverse QR codes sheet and joins the SunMint tree link), and
  3. runs scripts/build_index.py               (rebuilds qrs_index.json),

then commits + pushes to main ONLY if the working tree actually changed. A run
with nothing new is a clean no-op (no empty commit, no churn).

WHY: nothing scheduled the seeder, so the published JSON cache drifted from the
sheets (e.g. a bag linked to a tree kept status=SOLD until a manual run). This
mirrors the 30-minute sync_pending_caches.py cadence already on the autopilot box.

Usage (dry-run by default; --push to commit + push):
    GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json \
      python3 scripts/sync_lineage_assets.py --repo-dir /home/ubuntu/lineage-assets
    GITHUB_TOKEN=... python3 scripts/sync_lineage_assets.py --push

Env:
    GOOGLE_APPLICATION_CREDENTIALS  service-account JSON with read access to BOTH
                                    the Main Ledger and the SunMint sheet.
    GITHUB_TOKEN                    PAT with repo write (needed for --push).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_DIR = "/home/ubuntu/lineage-assets"
DEFAULT_CREDS = "/home/ubuntu/creds/agroverse-ledger-manager-google-credentials.json"
CLONE_URL = "https://github.com/TrueSightDAO/lineage-assets.git"
PUSH_URL = "https://x-access-token:{token}@github.com/TrueSightDAO/lineage-assets.git"
BRANCH = "main"
COMMIT_MSG = "chore(seed): sync qrs/ + qrs_index.json from sheets [skip ci]"


def _run(cmd: list, cwd: Path, env: dict | None = None, check: bool = True) -> int:
    print(f"[run] {' '.join(cmd)}", flush=True)
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if p.stdout:
        sys.stdout.write(p.stdout)
        if not p.stdout.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if check and p.returncode != 0:
        raise SystemExit(f"[fatal] command failed ({p.returncode}): {' '.join(cmd)}")
    return p.returncode


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo-dir",
        default=DEFAULT_REPO_DIR,
        help=f"working clone of lineage-assets (default: {DEFAULT_REPO_DIR})",
    )
    ap.add_argument(
        "--creds",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_CREDS),
        help="Google service-account JSON (read access to BOTH sheets)",
    )
    ap.add_argument(
        "--no-index",
        action="store_true",
        help="skip build_index.py (seed manifests only)",
    )
    ap.add_argument(
        "--push",
        action="store_true",
        help="commit + push when the tree is dirty (default: report only)",
    )
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    if not (repo / ".git").exists():
        raise SystemExit(
            f"[fatal] {repo} is not a git clone.\n        git clone {CLONE_URL} {repo}"
        )
    if not os.path.isfile(args.creds):
        raise SystemExit(f"[fatal] service-account JSON not found: {args.creds}")

    env = dict(os.environ)
    env["GOOGLE_APPLICATION_CREDENTIALS"] = args.creds

    # 1. land on a clean, current main
    _run(["git", "fetch", "--quiet", "origin", BRANCH], repo)
    _run(["git", "reset", "--hard", f"origin/{BRANCH}"], repo)
    _run(["git", "clean", "-fdq"], repo)

    # 2. rebuild manifests + index from the sheets
    _run([sys.executable, "scripts/seed_from_sheet.py", "--execute"], repo, env=env)
    if not args.no_index:
        _run([sys.executable, "scripts/build_index.py"], repo, env=env)

    # 3. commit only if something actually moved
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    ).stdout.strip()
    if not status:
        print("[done] sheets and cache already in sync \u2014 no changes.", flush=True)
        return

    changed = len([ln for ln in status.splitlines() if ln.strip()])
    print(f"[diff] {changed} path(s) changed", flush=True)
    _run(["git", "add", "-A"], repo)

    if not args.push:
        _run(["git", "diff", "--cached", "--stat"], repo, check=False)
        print(
            "[done] dry-run \u2014 pass --push to commit + push these changes.", flush=True
        )
        return

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("[fatal] --push needs GITHUB_TOKEN (or GH_TOKEN)")
    _run(["git", "commit", "-q", "-m", COMMIT_MSG], repo)
    _run(["git", "push", "-q", PUSH_URL.format(token=token), f"HEAD:{BRANCH}"], repo)
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    ).stdout.strip()
    print(f"[done] pushed {head} to origin/{BRANCH}", flush=True)


if __name__ == "__main__":
    main()
