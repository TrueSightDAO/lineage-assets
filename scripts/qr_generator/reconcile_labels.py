"""Reconcile lineage-assets manifests against the label PNG store.

`batch_compiler.py --only-missing-png` answers "which SHEET rows have no PNG"
(sheet -> pngs). It cannot answer the question that actually breaks a public
page: "which PUBLISHED manifests point at a label PNG that does not exist"
(manifest -> pngs). A page renders from the manifest, so a stale manifest whose
PNG was never committed (or was deleted) produces a QR page with no scannable
code while everything upstream looks healthy.

This script closes that gap. It is REPORT-ONLY by default: it prints a summary
and changes nothing, so it is safe to run against main at any time and safe to
wire into CI with --strict.

A manifest is MISSING when its `qr_image_url` resolves to a filename that is not
present in the label store. Writes are opt-in and deliberately narrow (--quarantine).
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


DEFAULT_MANIFEST_DIR = _REPO_ROOT / "qrs"
DEFAULT_PNGS_DIR = _REPO_ROOT / "pngs"


def image_token(url: str) -> str:
    """Filename stem a manifest's qr_image_url points at ('' when absent)."""
    if not url:
        return ""
    name = unquote(url.rsplit("/", 1)[-1])
    return name[:-4] if name.lower().endswith(".png") else name


def load_png_tokens(pngs_dir: Path) -> set:
    """Stems of every label PNG on disk. Matching is by stem, never by full
    path, so the check cannot be fooled by a differently-nested asset."""
    if not pngs_dir.is_dir():
        raise SystemExit(f"error: label store not found: {pngs_dir}")
    return {
        p.name[:-4]
        for p in pngs_dir.iterdir()
        if p.is_file() and p.name.lower().endswith(".png")
    }


def scan_manifests(manifest_dir: Path):
    """Yield (path, manifest_dict) for every parseable manifest.

    A malformed manifest is reported and skipped rather than aborting the scan:
    one corrupt JSON file must not hide the other 1,800 labels' status.
    """
    if not manifest_dir.is_dir():
        raise SystemExit(f"error: manifest dir not found: {manifest_dir}")
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"warn: unreadable manifest {path.name}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            yield path, data


def classify(manifest: dict, png_tokens: set) -> str:
    """One of: ok | no_url | missing | unparseable.

    `no_url` is distinct from `missing` on purpose -- a manifest with no
    qr_image_url was never asked to show a label (the page falls back to the
    placeholder by design), whereas `missing` is a manifest actively pointing at
    a file that is not there. Collapsing the two would overstate the defect.
    """
    token = image_token(manifest.get("qr_image_url", ""))
    if not token:
        return "no_url"
    return "ok" if token in png_tokens else "missing"


def build_report(
    manifest_dir: Path,
    pngs_dir: Path,
    *,
    asset_type=None,
    include_ok=False,
    exclude_pattern=None,
):
    """Return {rows, summary}. Pure apart from reading the two directories."""
    png_tokens = load_png_tokens(pngs_dir)
    pat = re.compile(exclude_pattern) if exclude_pattern else None
    rows = []
    for path, manifest in scan_manifests(manifest_dir):
        qr_id = manifest.get("qr_id") or path.stem
        state = classify(manifest, png_tokens)
        row = {
            "qr_id": qr_id,
            "asset_type": manifest.get("asset_type") or "unknown",
            "status": manifest.get("status") or "",
            "state": state,
            "qr_image_url": manifest.get("qr_image_url") or "",
            "manifest": path.name,
        }
        if asset_type and row["asset_type"] != asset_type:
            continue
        if pat and pat.search(qr_id):
            continue
        if state == "ok" and not include_ok:
            continue
        rows.append(row)

    by_type = Counter(r["asset_type"] for r in rows if r["state"] == "missing")
    summary = {
        "manifests_scanned": sum(1 for _ in scan_manifests(manifest_dir)),
        "pngs_on_disk": len(png_tokens),
        "reported": len(rows),
        "missing_total": sum(1 for r in rows if r["state"] == "missing"),
        "no_url_total": sum(1 for r in rows if r["state"] == "no_url"),
        "missing_by_asset_type": dict(sorted(by_type.items())),
    }
    return {"rows": rows, "summary": summary}


def print_human(report: dict, *, asset_type=None, exclude_pattern=None) -> None:
    s = report["summary"]
    scope = []
    if asset_type:
        scope.append(f"asset_type={asset_type}")
    if exclude_pattern:
        scope.append(f"exclude={exclude_pattern}")
    print(
        f"[reconcile] manifests={s['manifests_scanned']} labels_on_disk={s['pngs_on_disk']}"
        + (f" ({' '.join(scope)})" if scope else "")
    )
    print(
        f"[reconcile] MISSING label PNG: {s['missing_total']}"
        f" | manifest has no qr_image_url: {s['no_url_total']}"
    )
    if s["missing_by_asset_type"]:
        print(
            "[reconcile] missing by asset_type: "
            + ", ".join(f"{k}={v}" for k, v in s["missing_by_asset_type"].items())
        )
    if not report["rows"]:
        print("[reconcile] nothing to report")
        return
    grouped = defaultdict(list)
    for r in report["rows"]:
        grouped[(r["asset_type"], r["state"])].append(r)
    for atype, state in sorted(grouped):
        print(f"\n=== {atype} / {state} ({len(grouped[(atype, state)])}) ===")
        for r in grouped[(atype, state)]:
            print(f"  {r['qr_id']:<34} {r['status']:<12} {r['qr_image_url']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report manifests whose label PNG is absent (report-only by default)."
    )
    ap.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    ap.add_argument("--pngs-dir", default=str(DEFAULT_PNGS_DIR))
    ap.add_argument(
        "--asset-type", default=None, help="only this asset_type (e.g. cacao_bag, tree)"
    )
    ap.add_argument(
        "--exclude-pattern",
        default=None,
        help="regex of qr_ids to skip (e.g. test-code prefixes)",
    )
    ap.add_argument(
        "--include-ok",
        action="store_true",
        help="also list manifests whose label exists",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any label is missing (for CI)",
    )
    args = ap.parse_args(argv)

    report = build_report(
        Path(args.manifest_dir),
        Path(args.pngs_dir),
        asset_type=args.asset_type,
        include_ok=args.include_ok,
        exclude_pattern=args.exclude_pattern,
    )
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_human(
            report, asset_type=args.asset_type, exclude_pattern=args.exclude_pattern
        )

    return 1 if (args.strict and report["summary"]["missing_total"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
