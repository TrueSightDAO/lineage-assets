"""Resolve each SunMint row's coordinate through the approved chain, with caching.

Orchestrates the I/O around ``coord_resolution.resolve_coordinates``:

    fetch photo bytes -> exif_gps(bytes)                (step 1: camera ground truth)
                      -> burn-in read via Grok, cached   (step 2: Timemark overlay)
                      -> DApp-submitted lat/lng          (step 3: last resort)
                      -> resolve_coordinates(...)         (chain + sanity guard)

Burn-in reads cost a Grok vision call, so they are cached keyed on the photo's
sha256 (photos are immutable once published -> each photo is read at most once).
The number of Grok calls per run is hard-capped so a cold first run can never fan
out into an unbounded spend; when the cap is hit the burn-in step is simply
skipped for the remaining rows (and NOT cached), so a later run can still read them.

Burn-in reading is Grok-only (governor directive, Gary 2026-09-27) -- that lives in
``burnin_gps``; nothing here references Claude/Anthropic.
"""

from __future__ import annotations

import urllib.request

from burnin_gps import cache_key, read_burnin_text
from coord_resolution import DEFAULT_SANITY_METERS, exif_gps, resolve_coordinates

DEFAULT_MAX_LLM_CALLS = 60
FETCH_TIMEOUT_S = 30


def _default_fetch_bytes(url: str, timeout: int = FETCH_TIMEOUT_S) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def parse_submitted(lat_s, lng_s) -> tuple[float, float] | None:
    """Parse the DApp-submitted lat/lng cell strings. ``None`` unless both parse."""
    try:
        return (float(str(lat_s).strip()), float(str(lng_s).strip()))
    except (TypeError, ValueError):
        return None


class CoordResolver:
    """Per-run coordinate resolver: fetch -> EXIF -> cached Grok burn-in -> resolve.

    Collaborators are injectable so the whole orchestrator is unit-testable without
    network or Grok access.
    """

    _STAT_KEYS = (
        "fetched",
        "fetch_fail",
        "llm_calls",
        "llm_capped",
        "exif",
        "burnin",
        "submitted",
        "none",
    )

    def __init__(
        self,
        *,
        fetch_bytes=None,
        exif_fn=exif_gps,
        burnin_text_fn=read_burnin_text,
        cache: dict | None = None,
        grok_api_key: str | None = None,
        max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
        max_sanity_m: float = DEFAULT_SANITY_METERS,
    ) -> None:
        self._fetch = fetch_bytes or _default_fetch_bytes
        self._exif = exif_fn
        self._burnin_text = burnin_text_fn
        self._grok_api_key = grok_api_key
        self.cache = dict(cache or {})
        self.max_llm_calls = max_llm_calls
        self.max_sanity_m = max_sanity_m
        self._llm_calls = 0
        self.stats = dict.fromkeys(self._STAT_KEYS, 0)

    def _read_burnin_cached(self, data: bytes) -> str:
        """Return the burn-in text for ``data``, using the sha256-keyed cache.

        Returns ``""`` (without caching) when the LLM budget is exhausted, so a
        later run with budget can still read the photo.
        """
        key = cache_key(data)
        if key in self.cache:
            return self.cache[key]
        if self._llm_calls >= self.max_llm_calls:
            self.stats["llm_capped"] += 1
            return ""
        text = self._burnin_text(data, api_key=self._grok_api_key)
        self._llm_calls += 1
        self.stats["llm_calls"] += 1
        self.cache[key] = text
        return text

    def resolve(
        self, photo_url: str, lat_s, lng_s
    ) -> tuple[float | None, float | None, str]:
        """Resolve one row's coordinate. Returns ``(lat, lng, source)``.

        ``source`` is ``"exif"`` / ``"burnin"`` / ``"submitted"`` or ``""``.
        """
        submitted = parse_submitted(lat_s, lng_s)
        exif = None
        burnin_text = ""
        if photo_url:
            try:
                data = self._fetch(photo_url)
            except Exception:  # noqa: BLE001 - a bad URL must not abort the sync
                self.stats["fetch_fail"] += 1
                data = b""
            if data:
                self.stats["fetched"] += 1
                exif = self._exif(data)
                burnin_text = self._read_burnin_cached(data)
        lat, lng, source = resolve_coordinates(
            exif=exif,
            burnin_text=burnin_text,
            submitted=submitted,
            max_sanity_m=self.max_sanity_m,
        )
        self.stats[source or "none"] += 1
        return (lat, lng, source)

    def as_item_fn(self):
        """Return a ``(photo_url, lat_s, lng_s) -> (lat, lng, source)`` callable."""
        return self.resolve
