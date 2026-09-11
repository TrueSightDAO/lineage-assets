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
import re
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

# --- Header contract -------------------------------------------------------
# Canonical column layout for the `Agroverse QR codes` tab.
# Source of truth: tokenomics/SCHEMA.md -> "Sheet: `Agroverse QR codes`".
#
# WHY THIS GUARD EXISTS: every consumer of this sheet addresses columns
# POSITIONALLY (this seeder's COL map, process_qr_code_updates.gs's
# *_COL_DEST consts, process_sales_telegram_logs.gs, stripe_sales_sync.gs).
# Only newsletter_subscriber_sync.js resolves headers by name. So inserting
# or reordering a column silently writes the wrong field into the ledger
# with NO error anywhere. This converts that silent corruption into a
# hard stop at seed time.
#
# Comparison is whitespace-normalized + casefolded, because four headers
# legitimately contain embedded line breaks (M, N, U, W) and several are
# inconsistently cased (J, K, N, Q, R, Z).
EXPECTED_HEADERS: dict[int, str] = {
    0: "qr_code",
    1: "landing_page",
    2: "ledger",
    3: "status",
    4: "farm name",
    5: "state",
    6: "country",
    7: "Year",
    8: "Currency",
    9: "QR code creation date (YYYYMMDD)",
    10: "QR code location",
    11: "Owner Email",
    12: "Onboarding Email \nSent Date",
    13: "Tree Planting Date\n(YYYYMMDD)",
    14: "Latitude",
    15: "Longitude",
    16: "Planting Video URL",
    17: "Tree Seedling Photo URL",
    18: "Product Image",
    19: "Price",
    20: "Manager \nName",
    21: "Ledger Name",
    22: "Review Email \nSent Date",
    23: "Review Click Through Date",
    24: "Review Submit Date",
    25: "Stripe Session ID",
    26: "Sold Date",
    27: "Tree Planted Notification Sent Date",
}


def normalize_header(value: str) -> str:
    """Collapse all whitespace (incl. embedded newlines) and casefold."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def validate_headers(sheet_headers: list[str]) -> list[str]:
    """Return a list of human-readable header-drift problems ([] == contract OK)."""
    problems: list[str] = []
    width = max(len(EXPECTED_HEADERS), len(sheet_headers))
    for idx in range(width):
        want = EXPECTED_HEADERS.get(idx)
        got = sheet_headers[idx] if idx < len(sheet_headers) else None
        if want is None:
            if str(got or "").strip():
                problems.append(
                    f"  col#{idx}: UNEXPECTED column {got!r} (not in the documented layout)"
                )
            continue
        if got is None or not str(got).strip():
            problems.append(f"  col#{idx}: MISSING header (expected {want!r})")
            continue
        if normalize_header(got) != normalize_header(want):
            problems.append(f"  col#{idx}: expected {want!r} but found {got!r}")
    return problems


def _client() -> gspread.Client:
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not os.path.isfile(creds):
        sys.exit(
            "GOOGLE_APPLICATION_CREDENTIALS must point at a valid service account JSON"
        )
    return gspread.service_account(filename=creds)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=False)
    g.add_argument("--execute", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--allow-header-drift",
        action="store_true",
        default=False,
        help="Proceed even if row 1 does not match the documented header contract.",
    )
    args = p.parse_args()

    gc = _client()
    print(f"[info] Loading {QR_TAB} …")
    ws = gc.open_by_key(SHEET_ID).worksheet(QR_TAB)
    all_values = ws.get_all_values()
    if not all_values:
        sys.exit(f"[fatal] {QR_TAB} is empty")

    problems = validate_headers(all_values[0])
    if problems:
        print(
            "[fatal] Header row of %r does not match the documented contract:" % QR_TAB
        )
        for line in problems:
            print(line)
        print(
            "\nRefusing to seed: every consumer reads these columns positionally, so a\n"
            "shifted header would silently write the wrong values into the ledger.\n"
            "Fix the sheet (or update EXPECTED_HEADERS if tokenomics/SCHEMA.md changed).\n"
            "Override with --allow-header-drift ONLY if you have verified the drift."
        )
        if not args.allow_header_drift:
            sys.exit(1)
        print(
            "[warn] --allow-header-drift set; continuing despite the problems above.\n"
        )
    else:
        print(f"[info] header contract OK ({len(EXPECTED_HEADERS)} documented columns)")

    qr_rows = all_values[DATA_START_ROW - 1 :]
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

    print(
        f"\n[summary] created={created} updated={updated} unchanged={unchanged} skipped={skipped}"
    )
    if not args.execute:
        print("[summary] --dry-run (default). Pass --execute to write files.")


if __name__ == "__main__":
    main()
