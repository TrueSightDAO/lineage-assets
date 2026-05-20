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

QR_IMAGE_BASE = "https://raw.githubusercontent.com/TrueSightDAO/lineage-assets/main/pngs"
TRUESIGHT_QR_BASE = "https://truesight.me/qr"
EDGAR_RESOLVE_BASE = "https://edgar.truesight.me/agroverse/qr-code-check?qr_code="
SCHEMA_VERSION = "v0"

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

SEED_EVENT_TYPES = {"minted", "planted", "consigned", "sold"}


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


def build_manifest(row: list, source: str = "seed_from_sheet.py") -> dict | None:
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

    return {
        "qr_id":                qr_id,
        "asset_type":           asset_type,
        "schema_version":       SCHEMA_VERSION,
        "minted_at":            normalize_date(cell(row, "minted_at")),
        "minted_by":            manager,
        "status":               status,
        "current_holder":       current_holder,
        "lineage":              build_lineage(row, asset_type),
        "events":               build_events(row, asset_type),
        "owner_email_hash":     None,
        "current_landing_page": cell(row, "landing_page"),
        "qr_image_url":         f"{QR_IMAGE_BASE}/{safe_filename(qr_id)}.png",
        "scan_target":          f"{TRUESIGHT_QR_BASE}/?id={qr_id}",
        "edgar_resolve_url":    f"{EDGAR_RESOLVE_BASE}{qr_id}",
        "_seeded_at":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source":              source,
    }


def merge_preserve_events(existing: dict, fresh: dict) -> dict:
    existing_events = existing.get("events") or []
    custom_events = [e for e in existing_events if e.get("type") not in SEED_EVENT_TYPES]
    merged = dict(fresh)
    merged["events"] = fresh["events"] + custom_events
    return merged


def write_manifest(out_dir: Path, manifest: dict) -> tuple[Path, str]:
    """Write or merge a manifest. Returns (path, action) where action is
    'created', 'updated', or 'unchanged'."""
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
        path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        return path, "updated"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return path, "created"
