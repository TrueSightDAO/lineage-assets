#!/usr/bin/env python3
"""Generate the public pending-link JSON caches the dapp link_tree_planting page reads.

The dapp should read from public GitHub JSON caches (the review_queue convention),
NOT key-gated GAS endpoints. This script produces those caches:

  - sunmint_pending.json    {"status":"success","items":[{telegram_message_id,
                             submitted_name, planting_date, latitude, longitude,
                             species, status, submission_source, program}]}
                             -- SunMint rows with Status == NEW.
                             `submission_source` is the origin of the submission
                             (the app URL/host it was generated from, e.g.
                             https://cfr.truesight.me/). `program` is that origin
                             RESOLVED to a lineage-credentials program slug via the
                             registry (lineage-engine/scripts/
                             sunmint_program_registry.json) -- e.g. cfr.truesight.me
                             -> "crf-anapu". It is EMPTY when the submission is not
                             attributable to any registered program, so the dapp
                             program filter is a strict equality match: a tree shows
                             under a program only when its `program` equals it.
                             Both fields are host/sentinel-level, never a person.
  - sold_pending_tree.json  {"status":"success","items":[{qr_code, status, farm,
                             country, harvest_year, product, product_image, price,
                             owner_email_present, sheet_url, minted_at}]}
                             -- SOLD QR codes
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
QRS_INDEX_URL = (
    "https://raw.githubusercontent.com/TrueSightDAO/lineage-assets/main/qrs_index.json"
)
GH_API = "https://api.github.com/repos/TrueSightDAO/lineage-assets/contents/"
# host -> program slug (Option B attribution). Same registry the sibling
# lineage-engine/scripts/sync_sunmint_program_activity.py uses.
PROGRAM_REGISTRY_URL = (
    "https://raw.githubusercontent.com/TrueSightDAO/lineage-engine/main/"
    "scripts/sunmint_program_registry.json"
)
_URL_HOST_RE = re.compile(r"^[a-zA-Z][\w+.-]*://([^/?#]+)")

# SunMint tab columns (0-based): D=msg id, F=contribution (origin lives here),
# G=status date, J=submitted name, K=lat, L=lng, M=status, N=specie, R=linked QR
COL = {
    "msg_id": 3,
    "source": 5,
    "status_date": 6,
    "name": 9,
    "photo_url": 8,
    "latitude": 10,
    "longitude": 11,
    "status": 12,
    "species": 13,
    "linked_qr": 17,
}

# The submission origin is NOT a dedicated column: it rides inside the
# "Contribution Made" cell (col F), either as a "Submission Source: <url>" line or,
# in older rows, only in the "This submission was generated using <url>" footer.
# Mirrors the parsing already used by
# lineage-engine/scripts/sync_sunmint_program_activity.py so attribution agrees.
_SUBMISSION_SOURCE_RE = re.compile(
    r"^\s*[-*]?\s*Submission\s*Source\s*:\s*(.+?)\s*$", re.MULTILINE
)
_GENERATED_USING_RE = re.compile(r"generated using\s+(\S+)", re.IGNORECASE)


def _submission_source(text: str) -> str:
    """Return the submission origin (a URL or a sentinel like 'autopilot-sophia').

    Prefers an explicit ``Submission Source:`` line; falls back to the
    ``This submission was generated using <url>`` footer the older forms emit.
    Never returns anything but a host/URL/sentinel -- the cell around it can carry
    a base64 signature blob, which we must NOT leak into the public cache.
    """
    text = text or ""
    m = _SUBMISSION_SOURCE_RE.search(text)
    if m:
        return m.group(1).strip().strip('"').strip()
    m = _GENERATED_USING_RE.search(text)
    if m:
        return m.group(1).strip()
    return ""


def _source_host(value: str) -> str:
    """Normalise a Submission Source value to a lowercase host, when it is a URL.

    A non-URL sentinel (e.g. "autopilot-sophia") is returned lowercased unchanged,
    so it simply fails the host-registry lookup instead of raising. Mirrors
    lineage-engine/scripts/sync_sunmint_program_activity.py:source_host.
    """
    if not value:
        return ""
    m = _URL_HOST_RE.match(value.strip())
    if m:
        return m.group(1).lower()
    return value.strip().lower()


def _load_registry(payload: dict | None) -> dict:
    """Return {host: program_slug} from a fetched registry payload."""
    hosts = (payload or {}).get("hosts") or {}
    return {str(k).lower(): str(v) for k, v in hosts.items()}


def _resolve_program(submission_source: str, registry: dict) -> str:
    """Resolve a Submission Source to a program slug ('' when unregistered).

    The dapp filters strictly on this: an unattributable submission gets '' and
    therefore matches no program, rather than silently appearing under all.
    """
    return registry.get(_source_host(submission_source), "")


def _cell(row: list, key: str) -> str:
    idx = COL[key]
    return (row[idx] if idx < len(row) else "").strip()


def _iso_date(yyyymmdd: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", yyyymmdd.strip())
    if not m:
        return yyyymmdd.strip()
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _normalize_photo_url(url: str) -> str:
    """GitHub 'tree' URLs (browse HTML pages) are not renderable as <img>.
    Rewrite github.com/<o>/<r>/tree/<ref>/... -> raw.githubusercontent.com/<o>/<r>/<ref>/...
    """
    url = url.strip()
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    return url


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def _upload(path: str, payload: dict) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("--push needs GITHUB_TOKEN or GH_TOKEN")
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    # Fetch the current sha so the PUT updates (not fails) on an existing file.
    sha = None
    try:
        req0 = urllib.request.Request(GH_API + path, method="GET")
        req0.add_header("Authorization", f"Bearer {token}")
        req0.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req0, timeout=30) as r0:
            sha = json.load(r0).get("sha")
    except urllib.error.HTTPError:
        pass  # file may not exist yet — PUT without sha creates it
    data = json.dumps(
        {
            "message": f"cache(scripts): refresh {path} (sync_pending_caches.py)",
            "content": base64.b64encode(body.encode()).decode(),
            "sha": sha,
        }
    ).encode()
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


def build_sunmint_pending(rows: list, registry: dict | None = None) -> dict:
    registry = registry or {}
    items = []
    for row in rows:
        status = _cell(row, "status").upper()
        if status != "NEW":
            continue
        msg_id = _cell(row, "msg_id")
        if not msg_id:
            continue
        source = _submission_source(_cell(row, "source"))
        items.append(
            {
                "telegram_message_id": msg_id,
                "submitted_name": _cell(row, "name"),
                "planting_date": _iso_date(_cell(row, "status_date")),
                "photo_url": _normalize_photo_url(_cell(row, "photo_url")),
                "latitude": _cell(row, "latitude"),
                "longitude": _cell(row, "longitude"),
                "species": _cell(row, "species"),
                "status": "NEW",
                # Origin host/sentinel plus that origin RESOLVED to a program slug
                # ('' when not attributable). Host/sentinel only -- never a person.
                "submission_source": source,
                "program": _resolve_program(source, registry),
            }
        )
    return {"status": "success", "count": len(items), "items": items}


def build_sold_pending(rows: list, index: dict) -> dict:
    # Linked QR codes already claimed by a SunMint submission (col R, any status).
    linked = {_cell(r, "linked_qr") for r in rows if _cell(r, "linked_qr")}
    items = []
    for rec in index.get("qrs", []):
        if rec.get("status") not in ("SOLD", "TREE_PLANTING_FUNDS_TRANSFERRED"):
            continue
        if rec.get("asset_type") != "cacao_bag":
            continue  # tree records (BEC-era pk-* pledges) are trees themselves, not bags awaiting a link
        qr_id = rec.get("qr_id")
        if not qr_id or qr_id in linked:
            continue
        items.append(
            {
                "qr_code": qr_id,
                "status": rec.get("status", "SOLD"),
                "farm": rec.get("farm", ""),
                "country": rec.get("country", ""),
                "harvest_year": rec.get("harvest_year", ""),
                # Non-PII product context so the governor link page can show the
                # product image + the price it sold at (owner email stays out).
                "product": rec.get("product", ""),
                "product_image": rec.get("product_image", ""),
                "price": rec.get("price", ""),
                # Boolean only — never the email itself (PII stays out of the public cache).
                "owner_email_present": bool(rec.get("owner_email_present")),
                # Peppered blind-index token (HMAC-SHA256 of the email). Same email
                # -> same token, so the app can match "my bags" without the email
                # ever being stored or published. Empty when no pepper is set.
                "owner_email_hash": rec.get("owner_email_hash", "") or "",
                # Deep link to the ledger row (auth-gated by Google, not PII).
                "sheet_url": rec.get("sheet_url", ""),
                "minted_at": rec.get("minted_at", ""),
            }
        )
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
    registry = _load_registry(_fetch(PROGRAM_REGISTRY_URL))
    print(f"[info] program registry: {registry}")
    sunmint = build_sunmint_pending(rows, registry)
    print(f"[info] sunmint pending: {sunmint['count']}")

    sold = build_sold_pending(rows, index)
    print(f"[info] sold pending tree link: {sold['count']}")

    for path, payload in (
        ("sunmint_pending.json", sunmint),
        ("sold_pending_tree.json", sold),
    ):
        if args.push:
            _upload(path, payload)
        else:
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"[local] wrote ./{path}")


if __name__ == "__main__":
    main()
