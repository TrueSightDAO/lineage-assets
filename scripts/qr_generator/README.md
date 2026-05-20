# Agroverse QR Code Generator

## Batch QR Code Compilation

Automate the generation of labeled QR code images by fetching serials and farm names
from your Google Sheet, embedding each QR into a template, and annotating it above
with the farm name and below with the serial number.

### Prerequisites
- Python 3.x
All dependencies are listed in `requirements.txt`. Install them with:
```bash
pip install -r requirements.txt
```
Ensure your Google service account key file `gdrive_key.json` is present in the project root.

### Usage
```bash
 python3 batch_compiler.py \
   --credentials gdrive_key.json \
   --sheet-url "https://docs.google.com/spreadsheets/d/1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU/" \
   --sheet-name "Agroverse QR codes" \
   --output-dir package_qr_codes \
   --box-size 12 \
   --border 8 \
   --logo-ratio 0.25 \
   --font-family "/System/Library/Fonts/Helvetica.ttc"
```

Options:
- `--credentials`  Path to service account JSON file (default: `gdrive_key.json`)
- `--sheet-url`    Google Sheet URL (default as defined in `gdrive.py`)
- `--sheet-name`   Worksheet/tab name (default as defined in `gdrive.py`)
- `--template`     Template image for background (optional; omit to use white background)
- `--output-dir`   Directory to save compiled images (default: `package_qr_codes`)
- `--box-size`     QR code box size in pixels (default: 10)
- `--border`       QR code border width in boxes (default: 8)
- `--logo`         Path to logo image to embed at center of QR code (optional; default: `agroverse_logo.jpg`)
- `--logo-ratio`   Fraction of the QR code size for the logo (default: 0.2)
- `--no-logo`      Disable embedding logo in QR code
- `--font-family`  Font family to use for text (default: Helvetica)
- `--auto-continue` Automatically continue when encountering long QR codes without prompting (default: False)

Note: By default (no `--template`), the compiler outputs a 570×425 pixel image (5× the original 114×85), with the QR code fixed at 315×315 pixels (5× the original 63×63). Font sizes are dynamically chosen so that the Harvest, farm info, and planting message lines make good use of the 570px width. If you supply your own template, the output matches your template's dimensions and the QR scales to 30% of its width.
Additionally:
- The farm info line (`Farm, State, Country`) is rendered at 30% larger font size (no bold).
- The planting message (`Your tree is getting planted`) is rendered at 20% larger font size.
- Vertical spacing between text lines has been slightly increased for readability.

Compiled images will be saved as `compiled_<farm_name>_<serial>.png` in the output directory.

### QR Code Length Warning

The script automatically checks if QR codes exceed the recommended maximum length of **28 characters** (based on tested value: `2024OSCAR_2025051022_N_24`). 

**Behavior:**
- QR codes ≤ 28 characters: Processed normally ✅
- QR codes > 28 characters: Warning displayed with prompt to continue or skip ⚠️
- Use `--auto-continue` flag to bypass prompts and process all QR codes automatically

**Why it matters:**
Long QR codes create denser patterns that may not scan reliably on low-resolution label printers. The warning helps prevent printing issues before they occur.

**Example warning output:**
```
================================================================================
⚠️  WARNING: LONG QR CODE DETECTED
================================================================================
QR Code: 2024OSCAR_2025051022_N_24_EXTRA_LONG_SUFFIX
Farm: Sacred Earth Farms
Length: 42 characters (recommended maximum: 28)

Long QR codes may have scanning issues on low-resolution label printers.
The QR code will be more dense and may not scan reliably.

Tested working example: '2024OSCAR_2025051022_N_24' (28 chars)
================================================================================
Do you want to continue generating this QR code? [y/N]:
```