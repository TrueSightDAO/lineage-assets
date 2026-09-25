"""Shared manifest construction + IO for lineage-assets QR JSON files.

Both `seed_from_sheet.py` (bulk import from the Agroverse QR codes sheet)
and `qr_generator/batch_compiler.py` (per-mint generation) use these
functions so the produced JSON shape stays identical regardless of the
entry point.

Column mapping documented in scripts/seed_from_sheet.py + SCHEMA.md.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:  # imported as part of the `lib` package (seed_from_sheet.py)
    from .blind_index import compute_owner_email_hash
except ImportError:  # pragma: no cover - run as a top-level module
    from blind_index import compute_owner_email_hash  # type: ignore

QR_IMAGE_BASE = "https://raw.githubusercontent.com/TrueSightDAO/lineage-assets/main/pngs"
TRUESIGHT_QR_BASE = "https://truesight.me/qr"
EDGAR_RESOLVE_BASE = "https://edgar.truesight.me/agroverse/qr-code-check?qr_code="
SCHEMA_VERSION = "v0"

# The Agroverse QR codes tab in the Main Ledger. Safe to publish: the ledger is
# NOT publicly readable (anonymous export returns HTTP 401), so a deep link is a
# pointer that only resolves for a viewer who is ALREADY authorised — it leaks
# no PII. The sheet id + gid are already present elsewhere in this repo.
SHEET_ID = "1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU"
QR_TAB_GID = "472328231"  # tab: "Agroverse QR codes"

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

def cell(row: list, key: str) -> str:
    idx = COL[key]
    if idx >= len(row):
        return ""
    val = row[idx]
    return str(val).strip() if val is not None else ""


def safe_filename(qr_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", qr_id)


def normalize_date(raw: str):
    if not raw:
        return None
    s = raw.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    return s


def normalize_status(raw: str) -> str:
    s = (raw or "").upper().strip()
    if s in ("MINTED", "CONSIGNMENT", "SOLD", "RETIRED"):
        return s
    if s in ("", "PENDING"):
        return "MINTED"
    return s or "MINTED"


def infer_asset_type(row: list) -> str:
    if cell(row, "tree_planted_at") or cell(row, "latitude") or cell(row, "longitude"):
        return "tree"
    currency = cell(row, "currency").lower()
    if "tree" in currency:
        return "tree"
    if "drum" in currency or "instrument" in currency:
        return "drum"
    if "membership" in currency:
        return "membership"
    return "cacao_bag"


def build_lineage(row: list, asset_type: str) -> dict:
    base = {
        "farm":         cell(row, "farm"),
        "state":        cell(row, "state"),
        "country":      cell(row, "country"),
        "harvest_year": cell(row, "year"),
        "sku":          cell(row, "currency"),
        # Non-PII product context (cols S/T on the Agroverse QR codes sheet).
        # Surfaced so governor ops pages can show WHAT was sold without exposing
        # owner emails in the public cache.
        "product_image": cell(row, "product_image"),
        "price":         cell(row, "price"),
    }
    if asset_type == "tree":
        base.update({
            "planted_at":         normalize_date(cell(row, "tree_planted_at")),
            "latitude":           cell(row, "latitude"),
            "longitude":          cell(row, "longitude"),
            "planting_video_url": cell(row, "planting_video"),
            "seedling_photo_url": cell(row, "seedling_photo"),
            "location_text":      cell(row, "location"),
        })
    return base


def build_events(row: list, asset_type: str) -> list:
    events = []
    minted_at = normalize_date(cell(row, "minted_at"))
    manager = cell(row, "manager")
    ledger_name = cell(row, "ledger_name")
    status = normalize_status(cell(row, "status"))

    if minted_at or manager:
        events.append({
            "type":  "minted",
            "at":    minted_at,
            "by":    manager,
            "notes": "QR generated and registered on Agroverse QR codes sheet",
        })

    if asset_type == "tree":
        planted_at = normalize_date(cell(row, "tree_planted_at"))
        if planted_at:
            events.append({
                "type":  "planted",
                "at":    planted_at,
                "by":    manager,
                "notes": "Tree planted in the field",
            })

    if status == "CONSIGNMENT" and ledger_name:
        events.append({
            "type":  "consigned",
            "to":    ledger_name,
            "by":    manager,
            "notes": "Per Agroverse QR codes sheet status",
        })
    elif status == "SOLD":
        events.append({
            "type":  "sold",
            "by":    ledger_name or manager,
            "notes": "Per Agroverse QR codes sheet status",
        })
    return events


def build_manifest(
    row: list,
    source: str = "seed_from_sheet.py",
    tree_links: dict | None = None,
    sheet_row: int | None = None,
) -> dict | None:
    qr_id = cell(row, "qr_id")
    if not qr_id:
        return None
    asset_type = infer_asset_type(row)
    status = normalize_status(cell(row, "status"))
    manager = cell(row, "manager")
    ledger_name = cell(row, "ledger_name")

    current_holder = None
    if status == "CONSIGNMENT" and ledger_name:
        current_holder = {
            "partner_id":   ledger_name,
            "partner_name": ledger_name,
        }

    lineage = build_lineage(row, asset_type)
    # Mirror the SunMint Tree Planting linkage (col R -> col D) into the manifest
    # AT SEED TIME. Doing it here, rather than via a bolt-on sync, is what makes
    # the JSON cache self-regenerating: merge_preserve_events() keeps only the
    # fresh dict + custom events, so anything a separate script writes into
    # `lineage` afterwards is clobbered on the next re-seed.
    link = (tree_links or {}).get(qr_id)
    if link:
        entry = link if isinstance(link, dict) else {"tree_id": link}
        if entry.get("tree_id"):
            lineage["linked_tree"] = entry["tree_id"]
        if entry.get("linked_at"):
            lineage["linked_at"] = entry["linked_at"]

    return {
        "qr_id":                qr_id,
        "asset_type":           asset_type,
        "schema_version":       SCHEMA_VERSION,
        "minted_at":            normalize_date(cell(row, "minted_at")),
        "minted_by":            manager,
        "status":               status,
        "current_holder":       current_holder,
        "lineage":              lineage,
        "events":               build_events(row, asset_type),
        # Peppered blind index (HMAC-SHA256(pepper, normalized email)). Same
        # email -> same token, so the app can match "my bags" without the email
        # ever being stored or published. None when no OWNER_EMAIL_PEPPER is
        # configured (fail closed -- never emit an unpeppered hash).
        "owner_email_hash":     compute_owner_email_hash(cell(row, "owner_email")),
        # Non-PII signal: is this QR linked to a buyer/owner email at all?
        # A boolean derived from col L leaks NO PII but lets ops pages show a
        # "linked to owner" badge (e.g. an unlinked SOLD bag = sale not yet
        # attributed).
        "owner_email_present":  bool(cell(row, "owner_email")),
        # Deep link back to THIS row in the Main Ledger. Requires the viewer's
        # own Google auth (sheet is not public, 401 for anon), so it exposes no
        # PII while letting a governor jump straight to the owner's email.
        "sheet_row":            sheet_row,
        "sheet_url":            (
            f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
            f"#gid={QR_TAB_GID}&range=A{sheet_row}"
            if sheet_row
            else ""
        ),
        "current_landing_page": cell(row, "landing_page"),
        "qr_image_url":         f"{QR_IMAGE_BASE}/{safe_filename(qr_id)}.png",
        "scan_target":          f"{TRUESIGHT_QR_BASE}/?id={qr_id}",
        "edgar_resolve_url":    f"{EDGAR_RESOLVE_BASE}{qr_id}",
        "_seeded_at":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source":              source,
    }


def merge_preserve_events(existing: dict, fresh: dict) -> dict:
    """Merge a freshly-seeded manifest over the file already on disk.

    History is APPEND-ONLY. The seed regenerates only the events implied by the
    sheet's *current* state, but that state moves on. A bag that was `SOLD` and
    is later linked to a tree stops being `SOLD`, so a naive
    `fresh + custom` merge DROPS the `sold` event and rewrites history (this is
    the bug that erased `sold` from 2024OSCAR_CB_20260620_1).

    Here: any event recorded previously whose type the seed no longer emits is
    retained; events the seed still emits are refreshed in place; event types
    the seed emits for the first time are appended. Non-seed ("custom") events
    appended by other flows are retained as well.
    """
    existing_events = existing.get("events") or []
    fresh_events = fresh.get("events") or []
    fresh_by_type = {e.get("type"): e for e in fresh_events}

    merged_events: list = []
    emitted: set = set()
    for ev in existing_events:
        t = ev.get("type")
        if t in fresh_by_type and t not in emitted:
            merged_events.append(fresh_by_type[t])  # refresh in place
            emitted.add(t)
        else:
            merged_events.append(ev)                # retain history
    for ev in fresh_events:
        if ev.get("type") not in emitted:
            merged_events.append(ev)                # append a brand-new type
            emitted.add(ev.get("type"))

    merged = dict(fresh)
    merged["events"] = merged_events
    return merged


def write_manifest(
    out_dir: Path, manifest: dict, dry_run: bool = False
) -> tuple[Path, str]:
    """Write or merge a manifest. Returns (path, action) where action is
    'created', 'updated', or 'unchanged'.

    With ``dry_run=True`` the diff is still computed (so the action is REAL,
    not a guess) but nothing is written to disk."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe_filename(manifest['qr_id'])}.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}
        merged = merge_preserve_events(existing, manifest)
        existing_no_seeded = {k: v for k, v in existing.items() if k != "_seeded_at"}
        merged_no_seeded = {k: v for k, v in merged.items() if k != "_seeded_at"}
        if existing_no_seeded == merged_no_seeded:
            return path, "unchanged"
        if not dry_run:
            path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        return path, "updated"
    if not dry_run:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return path, "created"
