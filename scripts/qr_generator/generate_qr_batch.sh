#!/usr/bin/env bash
#
# ============================================================================
#  THIS IS HOW AGROVERSE / TRUESIGHT DAO QR CODES ARE GENERATED.
# ============================================================================
#
#  Do NOT hand-roll QR PNGs with the `qrcode` library, and do NOT reimplement
#  this in another repo (market_research, etc.). Add the row(s) to the
#  "Agroverse QR codes" tab on the Main Ledger, then run THIS script. It is
#  the canonical, parameter-locked wrapper around batch_compiler.py.
#
#  For each QR row on the sheet that does NOT already have a compiled image,
#  it writes (matching every other QR in the system):
#    - raw logo-embedded QR PNG    -> ../../pngs/<qr_id>.png      (what truesight.me/qr/?id=<id> shows)
#    - per-QR JSON manifest        -> ../../qrs/<qr_id>.json      (omit with --no-manifest if seeded already)
#    - print-ready compiled label  -> package_qr_codes/ + to_print/  (QR + center logo + farm copy + serial string)
#
#  The locked params (box-size 12, border 8, logo-ratio 0.25, Helvetica) are
#  what produce the standard look: logo in the middle of the QR, copy beneath,
#  serial string on the right. Changing them changes the house format.
#
#  Prereqs:
#    1. Run from this directory (lineage-assets/scripts/qr_generator/).
#    2. Auth: `gdrive_key.json` here (gitignored SA key with read on the Main
#       Ledger) OR export GOOGLE_APPLICATION_CREDENTIALS=<sa.json with sheet read>.
#    3. deps: pip install -r requirements.txt
#             (qrcode[pil], Pillow, google-api-python-client, gspread)
#
#  Minting NEW event/promo codes: add rows to the "Agroverse QR codes" tab
#  first (column A prefix convention: LA_ = Los Angeles, AUSTIN_, DTS_ =
#  Dual Tech Summit, …; CC = ceremonial cacao, CT = cacao tea; status SAMPLE
#  for display/promo). Then run this. It skips rows whose compiled image
#  already exists, so it only processes the new ones.
#
#  Usage:
#    ./generate_qr_batch.sh                 # generate for all un-compiled rows
#    ./generate_qr_batch.sh --auto-continue # don't prompt on long codes
#    ./generate_qr_batch.sh --no-manifest   # PNG/label only (manifests already seeded)
#  Extra args pass straight through to batch_compiler.py.
#
#  Doc: agentic_ai_context/LINEAGE_ASSETS.md  ·  batch_compiler.py --help
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

python3 batch_compiler.py \
  --credentials gdrive_key.json \
  --sheet-url "https://docs.google.com/spreadsheets/d/1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU/" \
  --sheet-name "Agroverse QR codes" \
  --output-dir package_qr_codes \
  --box-size 12 \
  --border 8 \
  --logo-ratio 0.25 \
  --font-family "/System/Library/Fonts/Helvetica.ttc" \
  "$@"
