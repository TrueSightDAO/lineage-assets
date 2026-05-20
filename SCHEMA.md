# Per-QR JSON schema

Each file in `qrs/` carries one QR-coded asset's full provenance. The
schema below is the v0 wrapper; per-asset-type fields extend `lineage`
and `events` without changing the wrapper.

## Wrapper (every file)

```jsonc
{
  "qr_id":         "string",     // matches filename (without .json)
  "asset_type":    "string",     // cacao_bag | tree | drum | membership | ...
  "schema_version": "v0",
  "minted_at":     "ISO 8601 timestamp",
  "minted_by":     "string",     // contributor name on the DAO contributors sheet
  "status":        "MINTED|CONSIGNMENT|SOLD|RETIRED",
  "current_holder": {            // null when not held by a partner (e.g. SOLD direct)
    "partner_id": "string",
    "partner_name": "string"
  },
  "lineage":   { ... type-specific ... },
  "events":    [ ... append-only history ... ],
  "qr_image_url": "string",      // raw.github URL into the qr_codes repo
  "scan_target":  "string",      // canonical truesight.me/qr/?id=<qr_id> URL
  "edgar_resolve_url": "string"  // edgar.truesight.me/agroverse/qr-code-check?qr_code=<qr_id>
}
```

## `events` array (every file)

Append-only history. Each event:

```jsonc
{
  "type":  "minted | consigned | sold | retired | restocked | <type-specific>",
  "at":    "ISO 8601 timestamp",
  "by":    "string (contributor name)",
  "to":    "string (recipient partner_id or contributor)",  // optional
  "notes": "string"                                         // optional
}
```

Events are append-only — never edit historical events, only append new
ones. If a status correction is needed, append a `corrected` event
referencing the prior event.

## Asset-type extensions

### `cacao_bag` (v0 — shipping today)

```jsonc
"lineage": {
  "farm":         "string",       // e.g. Fazenda Santa Ana
  "state":        "string",       // e.g. Bahia
  "country":      "string",       // e.g. Brazil
  "harvest_year": "string",       // e.g. 2024
  "sku":          "string"        // e.g. 8-ounce-organic-cacao-nibs
}
```

### `tree` (planned — Sunmint tree planting)

```jsonc
"lineage": {
  "farm":         "string",
  "location":     "string",       // GPS coordinates or area name
  "species":      "string",
  "planted_at":   "ISO 8601 date",
  "planter":      "string",
  "sponsor":      "string"        // optional — which cacao purchase financed it
}
```

### `drum` (planned — capoeira instrument provenance)

```jsonc
"lineage": {
  "maker":        "string",
  "wood_species": "string",
  "made_at":      "ISO 8601 date",
  "tradition":    "string"        // capoeira mestre lineage attribution
}
```

### `membership` (planned — DAO membership cards)

```jsonc
"lineage": {
  "contributor_name": "string",
  "joined_at":        "ISO 8601 date",
  "membership_tier":  "string"
}
```

## Adding a new asset type

1. Extend this doc with a new `lineage` block under "Asset-type extensions"
2. Pick an `asset_type` string value (snake_case, singular noun)
3. Add a render branch in `truesight_me_beta/qr/index.html` that recognises
   the new `asset_type` and renders the lineage block appropriately
4. No new path conventions, no new repos — just one new entry in this schema
   and one new render branch

The whole point of the JSON-per-QR + asset_type-as-field design is that new
asset types are an additive operation. The URL doesn't change. The folder
structure doesn't change. The renderer dispatches on the field.

## Versioning

`schema_version` is currently `v0`. When breaking changes happen:

- Bump to `v1` on new files
- Keep `v0` files readable; renderer handles both
- Document the migration in this file under a new "Version history" section
- Never silently rewrite existing files to a new schema version
