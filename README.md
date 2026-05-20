# lineage-assets

Per-asset provenance manifests for TrueSight DAO **physical assets** — cacao
bags, trees, drums, memberships, and future supply-chain assets.

Parallel architecture to [`lineage-credentials`](https://github.com/TrueSightDAO/lineage-credentials)
(which handles **humans + acts**). Same primitive — attested chain — different
population.

## What's here

- `qrs/<qr-id>.json` — one manifest per QR-coded asset. Each manifest carries
  the asset's full provenance: who minted it, what lineage it descends from
  (farm / batch / harvest year for cacao; planter / species for trees; etc.),
  current holder, append-only event history.
- `SCHEMA.md` — the per-QR JSON schema, asset-type extensions, examples.
- `scripts/seed_from_sheet.py` — one-time + ongoing sync from the
  `Agroverse QR codes` tab on the DAO Main Ledger spreadsheet. Generates one
  JSON file per row.

## How it's rendered

Each QR encodes a URL of the form
`https://edgar.truesight.me/agroverse/qr-code-check?qr_code=<id>` (existing
production pattern). Edgar resolves the QR's `landing_page` column from the
Main Ledger sheet and 302-redirects there.

Once the new provenance surface is reviewed and stable, the landing_page
values get bulk-updated to point at `https://truesight.me/qr/?id=<qr-id>`,
where the truesight.me template page reads the corresponding JSON from this
repo and renders the full provenance view.

Until that switch, existing scans continue to resolve to agroverse.shop
product pages unchanged — the new surface is built in parallel and
demo'd via direct URLs until Kirsten (and operator) sign off on the
experience.

## Naming convention

- `qrs/<qr-id>.json` — file name matches the QR code's serial ID exactly
  (the column A value from the `Agroverse QR codes` sheet). Examples:
  `2024OSCAR_20250826_NIBS_78.json`, `2025_20250829_4027ff6b.json`.
- Filenames are stable across asset types — adding trees / drums / memberships
  doesn't change the path shape. `asset_type` is a JSON field, not a path
  segment.

## Why JSON-per-QR, not aggregated

- Append-only events per asset — easy to diff one asset's history without
  pulling a large aggregate file
- Each file is independently fetchable by the truesight.me renderer (no
  index lookup needed)
- Git history per file = audit trail per asset
- Scales linearly with QR volume without performance cliff
- Mirrors the
  [`lineage-credentials`](https://github.com/TrueSightDAO/lineage-credentials)
  per-person-file pattern

## Reference

- `agentic_ai_context/CREDENTIALING_PLATFORM.md` — the lineage primitive
  described for the human side; same shape applies here
- `agentic_ai_context/GROWTH_MODEL.md` — where physical-asset provenance
  fits in the DAO's growth thesis (cross-jurisdiction supply-chain
  traceability is a 2027+ vector)
