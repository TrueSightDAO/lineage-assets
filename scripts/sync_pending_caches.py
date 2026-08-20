#!/usr/bin/env python3
"""Generate the public pending-link JSON caches the dapp link_tree_planting page reads.

The dapp should read from public GitHub JSON caches (the review_queue convention),
NOT key-gated GAS endpoints. This script produces those caches:

  - sunmint_pending.json    {"status":"success","items":[{telegram_message_id,
                             submitted_name, planting_date, latitude, longitude,
                             species, status}]}  -- SunMint rows with Status == NEW
  - sold_pending_tree.json  {"status":"success","items":[{qr_code, status, farm,
                             country, harvest_year, minted_at}]}  -- SOLD QR codes
                             whose qr_id is NOT yet linked to a SunMint submission
                             (col R "Linked QR Code" on the SunMint tab).

NO PII in these caches (public repo): owner emails are intentionally omitted.

Source of truth stays the Google Sheet; the JSON is a public mirror the dapp
fetches via raw.githubusercontent.com (same as dao_members.json in review_queue).

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json python3 scripts/sync_pending_caches.py --dry-run
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json GITHUB_TOKEN=... python3 scripts/sync_pending_caches.py --push
    (without --push the two JSON files are written locally to ./)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.request

import gspread

SOURCE_SHEET_ID = "1qbZZhf-_7xzmDTriaJVWj6OZshyQsFkdsAV8-pyzASQ"
SUNMINT_TAB = "SunMint Tree Planting"
QRS_INDEX_URL = "https://raw.githubusercontent.com/TrueSightDAO/lineage-assets/main/qrs_index.json"
GH_API = "https://api.github.com/repos/TrueSightDAO/lineage-assets/contents/"

# SunMint tab columns (0-based): D=msg id, G=status date, J=submitted name,
# K=lat, L=lng, M=status, N=specie, R=linked QR
COL = {"msg_id": 3, "status_date": 6, "name": 9, "latitude": 10,
       "longitude": 11, "status": 12, "species": 13, "linked_qr": 17}


def _cell(row: list, key: str) -> str:
    idx = COL[key]
    return (row[idx] if idx < len(row) else "").strip()


def _iso_date(yyyymmdd: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", yyyymmdd.strip())
    if not m:
        return yyyymmdd.strip()
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def _upload(path: str, payload: dict) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("--push needs GITHUB_TOKEN or GH_TOKEN")
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    data = json.dumps({
        "message": f"cache(scripts): refresh {path} (sync_pending_caches.py)",
        "content": base64.b64encode(body.encode()).decode(),
    }).encode()
    req = urllib.request.Request(GH_API + path, data=data, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[push] {path} -> {json.load(r).get('commit', {}).get('sha', '?')}")
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print(f"[push] {path} -> unchanged (already current)")
        else:
            raise


def build_sunmint_pending(rows: list) -> dict:
    items = []
    for row in rows:
        status = _cell(row, "status").upper()
        if status != "NEW":
            continue
        msg_id = _cell(row, "msg_id")
        if not msg_id:
            continue
        items.append({
            "telegram_message_id": msg_id,
            "submitted_name": _cell(row, "name"),
            "planting_date": _iso_date(_cell(row, "status_date")),
            "latitude": _cell(row, "latitude"),
            "longitude": _cell(row, "longitude"),
            "species": _cell(row, "species"),
            "status": "NEW",
        })
    return {"status": "success", "count": len(items), "items": items}


def build_sold_pending(rows: list, index: dict) -> dict:
    # Linked QR codes already claimed by a SunMint submission (col R, any status).
    linked = {_cell(r, "linked_qr") for r in rows if _cell(r, "linked_qr")}
    items = []
    for rec in index.get("qrs", []):
        if rec.get("status") != "SOLD":
            continue
        qr_id = rec.get("qr_id")
        if not qr_id or qr_id in linked:
            continue
        items.append({
            "qr_code": qr_id,
            "status": "SOLD",
            "farm": rec.get("farm", ""),
            "country": rec.get("country", ""),
            "harvest_year": rec.get("harvest_year", ""),
            "minted_at": rec.get("minted_at", ""),
        })
    return {"status": "success", "count": len(items), "items": items}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--push", action="store_true")
    args = p.parse_args()

    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not os.path.isfile(creds):
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS must point at a service account JSON")

    gc = gspread.service_account(filename=creds)
    ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet(SUNMINT_TAB)
    rows = ws.get_all_values()[1:]
    print(f"[info] {len(rows)} SunMint rows")

    sunmint = build_sunmint_pending(rows)
    print(f"[info] sunmint pending: {sunmint['count']}")

    index = _fetch(QRS_INDEX_URL)
    sold = build_sold_pending(rows, index)
    print(f"[info] sold pending tree link: {sold['count']}")

    for path, payload in (("sunmint_pending.json", sunmint),
                          ("sold_pending_tree.json", sold)):
        if args.push:
            _upload(path, payload)
        else:
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"[local] wrote ./{path}")


if __name__ == "__main__":
    main()
