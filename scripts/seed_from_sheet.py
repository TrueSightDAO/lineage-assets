#!/usr/bin/env python3
"""Seed lineage-assets/qrs/*.json from the Agroverse QR codes sheet.

Reads the `Agroverse QR codes` tab on the DAO Main Ledger spreadsheet
and emits one JSON file per QR row into ../qrs/<qr_id>.json. Idempotent;
preserves any non-seed events appended by other flows.

Manifest shape lives in lib/manifest.py — shared with batch_compiler.py
so seed and per-mint outputs are identical.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
      python3 scripts/seed_from_sheet.py --dry-run [--limit N]
    GOOGLE_APPLICATION_CREDENTIALS=... python3 scripts/seed_from_sheet.py --execute
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import gspread

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.manifest import build_manifest, write_manifest  # noqa: E402

SHEET_ID = "1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU"
QR_TAB = "Agroverse QR codes"
DATA_START_ROW = 2
OUT_DIR = _HERE.parent / "qrs"


def _client() -> gspread.Client:
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not os.path.isfile(creds):
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS must point at a valid service account JSON")
    return gspread.service_account(filename=creds)


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

    created = updated = unchanged = skipped = 0
    for row in qr_rows:
        manifest = build_manifest(row, source="seed_from_sheet.py")
        if manifest is None:
            skipped += 1
            continue
        if args.execute:
            _, action = write_manifest(OUT_DIR, manifest)
            if action == "created":
                created += 1
            elif action == "updated":
                updated += 1
            else:
                unchanged += 1
        else:
            # Dry-run: just count
            path = OUT_DIR / f"{manifest['qr_id']}.json"
            if path.is_file():
                unchanged += 1  # rough approximation; real run would diff
            else:
                created += 1

    print(f"\n[summary] created={created} updated={updated} unchanged={unchanged} skipped={skipped}")
    if not args.execute:
        print("[summary] --dry-run (default). Pass --execute to write files.")


if __name__ == "__main__":
    main()
