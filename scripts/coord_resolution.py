"""Coordinate resolution for SunMint tree submissions.

Governor-approved priority chain (Gary, 2026-09-27):

  1. EXIF GPS embedded in the submitted photo  (ground truth from the camera)
  2. Burned-in watermark GPS on the photo       (Timemark-style overlay)
  3. latitude/longitude submitted via the DApp  (last resort)

Why this exists: the DApp capture path re-encodes the photo through a
``<canvas>`` (``drawImage`` -> ``toBlob``), which STRIPS EXIF at capture time, and
the submitter's device GPS frequently returns one stale fix reused across an
entire batch. That collapses many genuinely-distinct trees onto a single identical
coordinate and makes the overpay co-location guard fire on roughly half the feed.

Safety: every non-submitted candidate is passed through a *sanity guard* -- a
candidate is only trusted when it lands within ``DEFAULT_SANITY_METERS`` of the
submitted coordinate. A vision-LLM reading the burn-in occasionally returns a
round-number placeholder (e.g. ``04 deg 04' 04" S 55 deg 55' 55" W``) that must
never be trusted as real GPS; the guard rejects it and we fall back down the chain.
"""

from __future__ import annotations

import io
import math
import re

EARTH_RADIUS_M = 6371000.0
DEFAULT_SANITY_METERS = 200.0

# Decimal-degrees hemisphere form, exactly as the Timemark overlay prints it:
#   "3.522803\u00b0S, 51.574812\u00b0W"
# Minimum 3 decimals so stray sheet numbers (e.g. the CEP "68365-000") can't match.
_DECIMAL_RE = re.compile(
    r"(\d{1,2}[.,]\d{3,8})\s*\u00b0?\s*([NS])\b\s*[,;]?\s*"
    r"(\d{1,3}[.,]\d{3,8})\s*\u00b0?\s*([EW])\b",
    re.IGNORECASE,
)

# Degrees/minutes/seconds form (some cameras / exports):
#   3\u00b0 31' 22.09" S  51\u00b0 34' 29.32" W
_DMS_RE = re.compile(
    r"(\d{1,3})\s*\u00b0\s*(\d{1,2})\s*['\u2032]\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"\u2033]?\s*([NS])\b"
    r"\s*[,;]?\s*"
    r"(\d{1,3})\s*\u00b0\s*(\d{1,2})\s*['\u2032]\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"\u2033]?\s*([EW])\b",
    re.IGNORECASE | re.DOTALL,
)


def _num(value) -> float:
    """Coerce a str / int / float / EXIF rational to float; ',' as decimal sep."""
    if isinstance(value, str):
        return float(value.replace(",", "."))
    return float(value)


def _dms(deg, minutes, seconds) -> float:
    return _num(deg) + _num(minutes) / 60.0 + _num(seconds) / 3600.0


def parse_gps_text(text: str) -> tuple[float, float] | None:
    """Extract (lat, lng) from a burn-in / overlay string. ``None`` if absent."""
    if not text:
        return None
    m = _DECIMAL_RE.search(text)
    if m:
        lat = _num(m.group(1))
        if m.group(2).upper() == "S":
            lat = -lat
        lng = _num(m.group(3))
        if m.group(4).upper() == "W":
            lng = -lng
        return (lat, lng)
    d = _DMS_RE.search(text)
    if d:
        lat = _dms(d.group(1), d.group(2), d.group(3))
        if d.group(4).upper() == "S":
            lat = -lat
        lng = _dms(d.group(5), d.group(6), d.group(7))
        if d.group(8).upper() == "W":
            lng = -lng
        return (lat, lng)
    return None


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two (lat, lng) points."""
    lat1, lon1 = a
    lat2, lon2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _gps_from_ifd(ifd) -> tuple[float, float] | None:
    """Read (lat, lng) from an EXIF GPS IFD. ``None`` when incomplete.

    GPS IFD tags: 1=LatRef, 2=Latitude (deg,min,sec), 3=LngRef, 4=Longitude.
    """
    if not ifd:
        return None
    try:
        lat_ref, lat_v = ifd.get(1), ifd.get(2)
        lng_ref, lng_v = ifd.get(3), ifd.get(4)
    except AttributeError:
        return None
    if not (lat_ref and lat_v and lng_ref and lng_v):
        return None
    lat = _dms(*lat_v)
    if str(lat_ref).upper() == "S":
        lat = -lat
    lng = _dms(*lng_v)
    if str(lng_ref).upper() == "W":
        lng = -lng
    return (lat, lng)


def exif_gps(data: bytes) -> tuple[float, float] | None:
    """Read GPS (lat, lng) from image bytes via EXIF. ``None`` when absent."""
    if not data:
        return None
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow is optional; degrade to no-EXIF
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            exif = im.getexif()
            if not exif:
                return None
            ifd = exif.get_ifd(0x8825)  # GPSInfo
    except Exception:  # noqa: BLE001 - malformed image => treat as no-EXIF
        return None
    return _gps_from_ifd(ifd) if ifd else None


def _sane(
    cand: tuple[float, float] | None,
    ref: tuple[float, float] | None,
    max_m: float,
) -> bool:
    if cand is None:
        return False
    if ref is None:
        return True  # nothing to sanity-check against
    return haversine_m(cand, ref) <= max_m


def resolve_coordinates(
    *,
    exif: tuple[float, float] | None = None,
    burnin_text: str = "",
    submitted: tuple[float, float] | None = None,
    max_sanity_m: float = DEFAULT_SANITY_METERS,
) -> tuple[float | None, float | None, str]:
    """Apply the priority chain. Returns ``(lat, lng, source)``.

    ``source`` is one of ``"exif"`` / ``"burnin"`` / ``"submitted"``, or ``""``
    when nothing at all is available. Candidates that fail the sanity guard are
    skipped, so a hallucinated burn-in degrades gracefully to the submitted value.
    """
    if exif and _sane(exif, submitted, max_sanity_m):
        return (exif[0], exif[1], "exif")
    burn = parse_gps_text(burnin_text)
    if burn and _sane(burn, submitted, max_sanity_m):
        return (burn[0], burn[1], "burnin")
    if submitted is not None:
        return (submitted[0], submitted[1], "submitted")
    return (None, None, "")


def format_coord(value: float | None) -> str:
    """Render a coordinate to a stable 6-dp string ('' when None)."""
    return "" if value is None else f"{value:.6f}"
