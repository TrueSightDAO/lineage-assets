#!/usr/bin/env python3
"""Seed lineage-assets/qrs/*.json from the Agroverse QR codes sheet.

Reads the `Agroverse QR codes` tab on the DAO Main Ledger spreadsheet
and emits one JSON file per QR row into ../qrs/<qr_id>.json.

The Agroverse QR codes sheet itself carries the per-QR provenance
(farm, state, country, year, mint date, manager, ledger, etc.) — no
join against Currencies needed for v0.

Idempotent: re-running updates existing files in place and creates new
ones for new rows. Events appended by non-seed flows (status corrections,
custom attestations) are preserved.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
      python3 scripts/seed_from_sheet.py --dry-run [--limit N]
    GOOGLE_APPLICATION_CREDENTIALS=... python3 scripts/seed_from_sheet.py --execute

Column mapping (verified against live sheet header row 2026-05-20):
    A=0  qr_code
    B=1  landing_page              (← what Edgar 302-redirects to today)
    C=2  ledger                    (URL or text)
    D=3  status                    (MINTED / CONSIGNMENT / SOLD)
    E=4  farm name
    F=5  state
    G=6  country
    H=7  Year                      (harvest year)
    I=8  Currency                  (full SKU description)
    J=9  QR code creation date     (YYYYMMDD or YYYY-MM-DD)
    K=10 QR code location          (physical location text)
    L=11 Owner Email
    M=12 Onboarding Email Sent Date
    N=13 Tree Planting Date        (YYYYMMDD; tree-asset only)
    O=14 Latitude                  (tree-asset only)
    P=15 Longitude                 (tree-asset only)
    Q=16 Planting Video URL        (tree-asset only)
    R=17 Tree Seedling Photo URL   (tree-asset only)
    S=18 Product Image
    T=19 Price
    U=20 Manager Name              (contributor who minted)
    V=21 Ledger Name               (consignee partner / sales channel)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import gspread

SHEET_ID = "1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU"
QR_TAB = "Agroverse QR codes"
DATA_START_ROW = 2
OUT_DIR = Path(__file__).resolve().parents[1] / "qrs"
QR_IMAGE_BASE = "https://raw.githubusercontent.com/TrueSightDAO/qr_codes/main"
TRUESIGHT_QR_BASE = "https://truesight.me/qr"
EDGAR_RESOLVE_BASE = "https://edgar.truesight.me/agroverse/qr-code-check?qr_code="

COL = {
    "qr_id":             0,
    "landing_page":      1,
    "ledger":            2,
    "status":            3,
    "farm":              4,
    "state":             5,
    "country":           6,
    "year":              7,
    "currency":          8,
    "minted_at":         9,
    "location":         10,
    "owner_email":      11,
    "onboarding_at":    12,
    "tree_planted_at":  13,
    "latitude":         14,
    "longitude":        15,
    "planting_video":   16,
    "seedling_photo":   17,
    "product_image":    18,
    "price":            19,
    "manager":          20,
    "ledger_name":      21,
}


def _client() -> gspread.Client:
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not os.path.isfile(creds):
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS must point at a valid service account JSON")
    return gspread.service_account(filename=creds)


def _cell(row: list, key: str) -> str:
    idx = COL[key]
    if idx >= len(row):
        return ""
    val = row[idx]
    return str(val).strip() if val is not None else ""


def _safe_filename(qr_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", qr_id)


def _normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    # Common YYYYMMDD
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # YYYY-MM-DD or with time
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    return s  # leave as-is; let renderer cope


def _normalize_status(raw: str) -> str:
    s = raw.upper().strip()
    if s in ("MINTED", "CONSIGNMENT", "SOLD", "RETIRED"):
        return s
    if s in ("", "PENDING"):
        return "MINTED"
    return s or "MINTED"


def _infer_asset_type(row: list) -> str:
    if _cell(row, "tree_planted_at") or _cell(row, "latitude") or _cell(row, "longitude"):
        return "tree"
    currency = _cell(row, "currency").lower()
    if "tree" in currency:
        return "tree"
    if "drum" in currency or "instrument" in currency:
        return "drum"
    if "membership" in currency:
        return "membership"
    return "cacao_bag"


def _build_lineage(row: list, asset_type: str) -> dict:
    base = {
        "farm":         _cell(row, "farm"),
        "state":        _cell(row, "state"),
        "country":      _cell(row, "country"),
        "harvest_year": _cell(row, "year"),
        "sku":          _cell(row, "currency"),
    }
    if asset_type == "tree":
        planted_raw = _cell(row, "tree_planted_at")
        base.update({
            "planted_at": _normalize_date(planted_raw),
            "latitude":   _cell(row, "latitude"),
            "longitude":  _cell(row, "longitude"),
            "planting_video_url": _cell(row, "planting_video"),
            "seedling_photo_url": _cell(row, "seedling_photo"),
            "location_text":      _cell(row, "location"),
        })
    return base


def _build_events(row: list, asset_type: str) -> list[dict]:
    events: list[dict] = []
    minted_at = _normalize_date(_cell(row, "minted_at"))
    manager = _cell(row, "manager")
    ledger_name = _cell(row, "ledger_name")
    status = _normalize_status(_cell(row, "status"))

    if minted_at or manager:
        events.append({
            "type": "minted",
            "at":   minted_at,
            "by":   manager,
            "notes": "QR generated and registered on Agroverse QR codes sheet",
        })

    if asset_type == "tree":
        planted_at = _normalize_date(_cell(row, "tree_planted_at"))
        if planted_at:
            events.append({
                "type": "planted",
                "at":   planted_at,
                "by":   manager,
                "notes": "Tree planted in the field",
            })

    if status == "CONSIGNMENT" and ledger_name:
        events.append({
            "type": "consigned",
            "to":   ledger_name,
            "by":   manager,
            "notes": "Per Agroverse QR codes sheet status",
        })
    elif status == "SOLD":
        events.append({
            "type": "sold",
            "by":   ledger_name or manager,
            "notes": "Per Agroverse QR codes sheet status",
        })

    return events


def _build_manifest(row: list) -> dict | None:
    qr_id = _cell(row, "qr_id")
    if not qr_id:
        return None
    asset_type = _infer_asset_type(row)
    status = _normalize_status(_cell(row, "status"))
    manager = _cell(row, "manager")
    ledger_name = _cell(row, "ledger_name")

    current_holder = None
    if status == "CONSIGNMENT" and ledger_name:
        current_holder = {
            "partner_id":   ledger_name,
            "partner_name": ledger_name,
        }

    return {
        "qr_id":              qr_id,
        "asset_type":         asset_type,
        "schema_version":     "v0",
        "minted_at":          _normalize_date(_cell(row, "minted_at")),
        "minted_by":          manager,
        "status":             status,
        "current_holder":     current_holder,
        "lineage":            _build_lineage(row, asset_type),
        "events":             _build_events(row, asset_type),
        "owner_email_hash":   None,  # privacy: don't expose raw owner email; reserved for future
        "current_landing_page": _cell(row, "landing_page"),  # what Edgar redirects to today
        "qr_image_url":       f"{QR_IMAGE_BASE}/{_safe_filename(qr_id)}.png",
        "scan_target":        f"{TRUESIGHT_QR_BASE}/?id={qr_id}",
        "edgar_resolve_url":  f"{EDGAR_RESOLVE_BASE}{qr_id}",
        "_seeded_at":         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source":            "seed_from_sheet.py",
    }


def _merge_preserve_events(existing: dict, fresh: dict) -> dict:
    existing_events = existing.get("events") or []
    seed_event_types = {"minted", "planted", "consigned", "sold"}
    custom_events = [e for e in existing_events if e.get("type") not in seed_event_types]
    merged = dict(fresh)
    merged["events"] = fresh["events"] + custom_events
    return merged


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=False)
    g.add_argument("--execute", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    gc = _client()
    print(f"[info] Loading {QR_TAB} …")
    ws = gc.open_by_key(SHEET_ID).worksheet(QR_TAB)
    qr_rows = ws.get_all_values()[DATA_START_ROW - 1:]
    print(f"[info] {len(qr_rows)} QR rows to process")

    if args.limit:
        qr_rows = qr_rows[: args.limit]
        print(f"[info] limited to first {len(qr_rows)} rows")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    created = updated = skipped = unchanged = 0
    for row in qr_rows:
        manifest = _build_manifest(row)
        if manifest is None:
            skipped += 1
            continue
        path = OUT_DIR / f"{_safe_filename(manifest['qr_id'])}.json"
        if path.is_file():
            try:
                existing = json.loads(path.read_text())
            except Exception:
                existing = {}
            existing_no_seeded = {k: v for k, v in existing.items() if k != "_seeded_at"}
            merged = _merge_preserve_events(existing, manifest)
            merged_no_seeded = {k: v for k, v in merged.items() if k != "_seeded_at"}
            if existing_no_seeded == merged_no_seeded:
                unchanged += 1
                continue
            if args.execute:
                path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
            updated += 1
        else:
            if args.execute:
                path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            created += 1

    print(f"\n[summary] created={created} updated={updated} unchanged={unchanged} skipped={skipped}")
    if not args.execute:
        print("[summary] --dry-run (default). Pass --execute to write files.")


if __name__ == "__main__":
    main()
