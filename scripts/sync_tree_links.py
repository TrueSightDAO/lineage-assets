#!/usr/bin/env python3
"""Mirror LINKED SunMint tree-planting rows into lineage-assets JSON and cross-link QR <-> tree.

Reads the `SunMint Tree Planting` tab on the Telegram Chat Logs spreadsheet
(SOURCE, `1qbZZhf...`) and, for every row whose Status (col M) is `LINKED`:

- mints/updates the **tree** JSON record `qrs/<pk-sunmint_msgid>.json`
  (asset_type `tree`) with species / planted_at / lat-long / planter and
  `sponsor_qr` = the linked QR code (col R `Linked QR Code`);
- patches the **QR** JSON record `qrs/<qr_code>.json` (asset_type `cacao_bag`)
  adding `lineage.linked_tree` = the tree record id + an `assigned_to_tree` event.

This gives Gary's ask: the QR JSON record links to the GitHub JSON record of
the tree (and vice-versa). The Google Sheet remains the source of truth; the
JSON cache is a machine-readable mirror (same pattern as seed_from_sheet.py).

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
      python3 scripts/sync_tree_links.py --dry-run [--limit N]
    GOOGLE_APPLICATION_CREDENTIALS=... python3 scripts/sync_tree_links.py --execute
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

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.manifest import safe_filename  # noqa: E402

SOURCE_SHEET_ID = "1qbZZhf-_7xzmDTriaJVWj6OZshyQsFkdsAV8-pyzASQ"
SUNMINT_TAB = "SunMint Tree Planting"
DATA_START_ROW = 2
OUT_DIR = _HERE.parent / "qrs"

# Column indexes (0-based) on the SunMint Tree Planting tab (plan 1.1):
# A Telegram Update ID, B Chatroom ID, C Chatroom Name, D Telegram Message ID (stable key),
# E Contributor Handle, F Contribution Made, G Status date (YYYYMMDD), H Telegram File IDs,
# I Photo URL, J Submitted Name, K Latitude, L Longitude, M Status, N Specie,
# O GitHub Commit URL, P Cost of Tree, Q Tree Planting Time,
# R Linked QR Code (new), S Linked At (new)
COL = {
    "msg_id": 3,  # D
    "status_date": 6,  # G
    "photo": 8,  # I
    "name": 9,  # J
    "latitude": 10,  # K
    "longitude": 11,  # L
    "status": 12,  # M
    "species": 13,  # N
    "linked_qr": 17,  # R
}

SCHEMA_VERSION = "v0"
TRUESIGHT_QR_BASE = "https://truesight.me/qr"
EDGAR_RESOLVE_BASE = "https://edgar.truesight.me/agroverse/qr-code-check?qr_code="


def _client() -> gspread.Client:
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not os.path.isfile(creds):
        sys.exit(
            "GOOGLE_APPLICATION_CREDENTIALS must point at a valid service account JSON"
        )
    return gspread.service_account(filename=creds)


def _cell(row: list, key: str) -> str:
    idx = COL[key]
    return (row[idx] if idx < len(row) else "").strip()


def _iso_date(yyyymmdd: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", yyyymmdd.strip())
    if not m:
        return yyyymmdd.strip()
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}"


def _tree_id(msg_id: str) -> str:
    """Deterministic tree record id: pk-<sunmint message id> (matches pk-* convention)."""
    return f"pk-{msg_id}"


def _base_wrapper(qr_id: str, asset_type: str) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "qr_id": qr_id,
        "asset_type": asset_type,
        "schema_version": SCHEMA_VERSION,
        "minted_at": now,
        "minted_by": "sync_tree_links.py",
        "status": "MINTED",
        "current_holder": None,
        "lineage": {},
        "events": [],
        "owner_email_hash": None,
        "current_landing_page": "",
        "qr_image_url": "",
        "scan_target": f"{TRUESIGHT_QR_BASE}/?id={qr_id}",
        "edgar_resolve_url": f"{EDGAR_RESOLVE_BASE}{qr_id}",
        "_seeded_at": now,
        "_source": "sync_tree_links.py",
    }


def _merge(existing: dict, fresh: dict) -> dict:
    """Merge fresh into existing, preserving non-sync events (like merge_preserve_events)."""
    merged = dict(existing)
    merged.update({k: v for k, v in fresh.items() if v is not None and v != ""})
    # Preserve any events not written by this script.
    sync_types = {"minted", "linked", "assigned_to_tree"}
    kept = [
        e for e in (existing.get("events") or []) if e.get("type") not in sync_types
    ]
    merged["events"] = (fresh.get("events") or []) + kept
    return merged


def _write(qr_id: str, fresh: dict) -> tuple[Path, str]:
    path = OUT_DIR / f"{safe_filename(qr_id)}.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}
        merged = _merge(existing, fresh)
        if existing == merged:
            return path, "unchanged"
        path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        return path, "updated"
    path.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n")
    return path, "created"


def build_tree_record(row: list) -> dict | None:
    msg_id = _cell(row, "msg_id")
    linked_qr = _cell(row, "linked_qr")
    if not msg_id or not linked_qr:
        return None
    tree_id = _tree_id(msg_id)
    rec = _base_wrapper(tree_id, "tree")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["minted_at"] = now
    rec["status"] = "ASSIGNED_TO_TREE"
    rec["lineage"] = {
        "farm": "SunMint",
        "location": f"{_cell(row, 'latitude')},{_cell(row, 'longitude')}".strip(","),
        "species": _cell(row, "species"),
        "planted_at": _iso_date(_cell(row, "status_date")),
        "planter": _cell(row, "name"),
        "sponsor_qr": linked_qr,
        "planting_photo_url": _cell(row, "photo"),
    }
    rec["events"] = [
        {
            "type": "minted",
            "at": now,
            "by": "sync_tree_links.py",
            "notes": "SunMint tree-planting submission mirrored",
        },
        {
            "type": "linked",
            "at": now,
            "by": linked_qr,
            "notes": f"linked to sold QR {linked_qr}",
        },
    ]
    return rec


def build_qr_patch(row: list) -> dict | None:
    msg_id = _cell(row, "msg_id")
    linked_qr = _cell(row, "linked_qr")
    if not msg_id or not linked_qr:
        return None
    tree_id = _tree_id(msg_id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = _base_wrapper(linked_qr, "cacao_bag")
    rec["lineage"] = {"linked_tree": tree_id, "linked_at": now}
    rec["events"] = [
        {
            "type": "assigned_to_tree",
            "at": now,
            "by": "sync_tree_links.py",
            "notes": f"linked to tree {tree_id}",
        },
    ]
    return rec


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=False)
    g.add_argument("--execute", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    gc = _client()
    print(f"[info] Loading {SUNMINT_TAB} …")
    ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet(SUNMINT_TAB)
    rows = ws.get_all_values()[DATA_START_ROW - 1 :]
    print(f"[info] {len(rows)} SunMint rows to scan")

    linked_rows = [r for r in rows if _cell(r, "status").upper() == "LINKED"]
    print(f"[info] {len(linked_rows)} LINKED rows")
    if args.limit:
        linked_rows = linked_rows[: args.limit]
        print(f"[info] limited to first {len(linked_rows)} LINKED rows")

    created = updated = unchanged = skipped = 0
    for row in linked_rows:
        tree = build_tree_record(row)
        qr = build_qr_patch(row)
        if tree is None or qr is None:
            skipped += 1
            continue
        if args.execute:
            _, ta = _write(tree["qr_id"], tree)
            _, qa = _write(qr["qr_id"], qr)
            created += (ta == "created") + (qa == "created")
            updated += (ta == "updated") + (qa == "updated")
            unchanged += (ta == "unchanged") + (qa == "unchanged")
        else:
            tree_path = OUT_DIR / f"{safe_filename(tree['qr_id'])}.json"
            qr_path = OUT_DIR / f"{safe_filename(qr['qr_id'])}.json"
            created += 0 if tree_path.is_file() else 1
            created += 0 if qr_path.is_file() else 1
            unchanged += (1 if tree_path.is_file() else 0) + (
                1 if qr_path.is_file() else 0
            )

    print(
        f"\n[summary] created={created} updated={updated} unchanged={unchanged} skipped={skipped}"
    )
    if not args.execute:
        print("[summary] --dry-run (default). Pass --execute to write files.")


if __name__ == "__main__":
    main()
