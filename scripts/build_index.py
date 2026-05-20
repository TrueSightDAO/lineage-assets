#!/usr/bin/env python3
"""Aggregate all per-QR manifests under qrs/ into a single qrs_index.json.

Powers truesight.me/physical-assets/serialized (the Product Verification
listing page) and any LLM agent that wants a single-fetch view of every
QR in the system without enumerating 1000s of individual files.

Output schema (one entry per QR):
    {
      "qr_id": "...",
      "asset_type": "cacao_bag | tree | drum | membership | ...",
      "status": "MINTED | CONSIGNMENT | SOLD | RETIRED",
      "farm": "...",
      "country": "...",
      "minted_at": "YYYY-MM-DD",
      "current_holder": "partner name" | null,
      "scan_target": "https://truesight.me/qr/?id=<qr_id>"
    }

Usage:
    python3 scripts/build_index.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QRS_DIR = HERE.parent / "qrs"
OUT_PATH = HERE.parent / "qrs_index.json"


def _row_for(manifest: dict) -> dict:
    holder = manifest.get("current_holder") or None
    holder_name = None
    if holder:
        holder_name = holder.get("partner_name") or holder.get("partner_id")
    lineage = manifest.get("lineage") or {}
    return {
        "qr_id":          manifest.get("qr_id", ""),
        "asset_type":     manifest.get("asset_type", "unknown"),
        "status":         manifest.get("status", "MINTED"),
        "farm":           lineage.get("farm", "") or "",
        "country":        lineage.get("country", "") or "",
        "harvest_year":   lineage.get("harvest_year", "") or "",
        "minted_at":      manifest.get("minted_at", "") or "",
        "current_holder": holder_name,
        "scan_target":    manifest.get("scan_target",
                                       f"https://truesight.me/qr/?id={manifest.get('qr_id', '')}"),
    }


def main() -> None:
    if not QRS_DIR.is_dir():
        raise SystemExit(f"missing qrs dir: {QRS_DIR}")

    rows = []
    bad = 0
    for path in sorted(QRS_DIR.glob("*.json")):
        try:
            manifest = json.loads(path.read_text())
        except Exception:
            bad += 1
            continue
        rows.append(_row_for(manifest))

    # Sort newest mints first; manifests without minted_at fall to the bottom
    rows.sort(key=lambda r: (r.get("minted_at") or "", r.get("qr_id") or ""), reverse=True)

    payload = {
        "generated_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":        "build_index.py",
        "qr_count":      len(rows),
        "by_status":     _count_by(rows, "status"),
        "by_asset_type": _count_by(rows, "asset_type"),
        "qrs":           rows,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"[done] wrote {len(rows)} rows to {OUT_PATH}  (skipped {bad} unparseable files)")


def _count_by(rows: list[dict], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        key = str(r.get(field) or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


if __name__ == "__main__":
    main()
