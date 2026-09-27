"""Read burned-in (watermark) GPS text from a tree-planting photo via Grok vision.

Governor directive (Gary, 2026-09-27): burn-in GPS extraction MUST use **Grok**
(x.ai) -- NOT Claude/Anthropic. This module is the ONLY place a photo is sent to a
vision model for coordinate reading; it deliberately speaks the x.ai chat API.

Step 2 of the coordinate chain in ``coord_resolution.resolve_coordinates``
(EXIF > burn-in > DApp-submitted). CFR submissions carry a semi-transparent
Timemark overlay printing ``3.522803S, 51.574812W`` + date + place; tesseract
misses this stylized overlay but a vision model reads it cleanly.

Reliability guards (a vision read must never be blindly trusted):
  * the prompt forbids guessing and asks for ``UNSURE`` when nothing is legible;
  * the raw text is parsed by ``coord_resolution.parse_gps_text`` (format gate);
  * the caller applies the proximity sanity guard in ``resolve_coordinates``.

Cost control: photos are immutable once published, so callers cache the raw text
keyed on the photo's sha256 -- each photo is read at most once.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import urllib.request

from coord_resolution import parse_gps_text

GROK_ENDPOINT = "https://api.x.ai/v1/chat/completions"
DEFAULT_GROK_MODEL = "grok-4-1-fast-non-reasoning"
MAX_SIDE = 1600  # downscale before the vision call, mirroring farm-media-daemon
JPEG_QUALITY = 82
TIMEOUT_S = 60

PROMPT = (
    "This photo may have a semi-transparent camera watermark (for example a "
    "'Timemark' overlay) burned into a corner that prints GPS coordinates. "
    "Read ONLY that watermark. If present, reply with the latitude and longitude "
    "exactly as printed, on a single line, e.g. '3.522803S, 51.574812W'. "
    "If no watermark or GPS is legible, reply exactly 'UNSURE'. "
    "Do not guess or invent coordinates."
)


def _prepare_b64(image_bytes: bytes) -> str:
    """Downscale + JPEG-encode for the vision call; fall back to raw base64."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow optional; send raw bytes instead
        return base64.b64encode(image_bytes).decode("ascii")
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - undecodable image => send raw bytes
        return base64.b64encode(image_bytes).decode("ascii")


def _extract_content(resp: dict) -> str:
    """Pull the assistant text out of an OpenAI-style chat completion."""
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _http_post_json(url: str, headers: dict, payload: dict) -> dict:
    """Default transport: POST JSON, return parsed JSON. Injectable for tests."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={**headers, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def read_burnin_text(
    image_bytes: bytes,
    *,
    api_key: str | None = None,
    transport=None,
    model: str | None = None,
    prompt: str = PROMPT,
) -> str:
    """Return the raw watermark reading for a photo (``""`` when unavailable).

    Uses Grok only. Never raises: a missing key, transport error, or empty photo
    degrades to ``""`` so the caller falls through to the DApp-submitted coord.
    """
    api_key = api_key or os.environ.get("GROK_API_KEY")
    if not api_key or not image_bytes:
        return ""
    model = model or os.environ.get("BURNIN_GROK_MODEL", DEFAULT_GROK_MODEL)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{_prepare_b64(image_bytes)}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 400,
        "temperature": 0.1,
    }
    call = transport or _http_post_json
    try:
        resp = call(GROK_ENDPOINT, {"Authorization": f"Bearer {api_key}"}, payload)
    except Exception:  # noqa: BLE001 - network/API failure => no burn-in reading
        return ""
    return _extract_content(resp).strip()


def burnin_gps(
    image_bytes: bytes,
    *,
    api_key: str | None = None,
    transport=None,
    model: str | None = None,
) -> tuple[float, float] | None:
    """Read + parse a burn-in coordinate. ``None`` when absent or unreadable.

    Returns ``None`` for the explicit ``UNSURE`` reply and for any text that does
    not match a GPS pattern -- never a made-up guess.
    """
    text = read_burnin_text(
        image_bytes, api_key=api_key, transport=transport, model=model
    )
    if not text or text.strip(" .").upper() == "UNSURE":
        return None
    return parse_gps_text(text)


def cache_key(image_bytes: bytes) -> str:
    """Stable cache key for an immutable photo (its sha256)."""
    return hashlib.sha256(image_bytes).hexdigest()


def load_cache(path: str) -> dict:
    """Load the burn-in text cache (``{}`` when missing or corrupt)."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path: str, cache: dict) -> None:
    """Atomically persist the cache so a crash can't leave it half-written."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
