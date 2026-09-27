"""Coordinate pipeline: EXIF > burn-in (Grok, cached) > submitted, with guards."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from coord_pipeline import CoordResolver, parse_submitted
from sync_pending_caches import build_sunmint_pending

# --- fake collaborators -----------------------------------------------------
SUB = (-3.5229189, -51.5749705)  # the stale batch coordinate
NEAR = (-3.522803, -51.574812)  # ~21 m away (real burn-in position)
FAR = (-4.068, -55.932)  # the 04d04'04" placeholder hallucination


def _fetch(data=b"IMG"):
    calls = []

    def f(url):
        calls.append(url)
        return data

    f.calls = calls
    return f


def test_parse_submitted_ok_and_bad():
    assert parse_submitted("-3.5", "-51.5") == (-3.5, -51.5)
    assert parse_submitted("", "") is None
    assert parse_submitted("abc", "-51.5") is None
    assert parse_submitted(None, None) is None


def test_exif_wins_when_present():
    r = CoordResolver(
        fetch_bytes=_fetch(),
        exif_fn=lambda d: NEAR,
        burnin_text_fn=lambda d, api_key=None: "3.52S, 51.57W",
    )
    lat, _lng, src = r.resolve("http://p/x.jpg", *map(str, SUB))
    assert src == "exif"
    assert lat == pytest.approx(NEAR[0])


def test_burnin_used_when_no_exif():
    r = CoordResolver(
        fetch_bytes=_fetch(),
        exif_fn=lambda d: None,
        burnin_text_fn=lambda d, api_key=None: "3.522803\u00b0S, 51.574812\u00b0W",
    )
    lat, lng, src = r.resolve("http://p/x.jpg", *map(str, SUB))
    assert src == "burnin"
    assert lat == pytest.approx(NEAR[0])
    assert lng == pytest.approx(NEAR[1])


def test_hallucinated_burnin_falls_back_to_submitted():
    r = CoordResolver(
        fetch_bytes=_fetch(),
        exif_fn=lambda d: None,
        burnin_text_fn=lambda d, api_key=None: "04\u00b004'04\"S 55\u00b055'55\"W",
    )
    lat, lng, src = r.resolve("http://p/x.jpg", *map(str, SUB))
    assert src == "submitted"
    assert (lat, lng) == SUB


def test_no_photo_url_is_submitted():
    r = CoordResolver(fetch_bytes=_fetch(), exif_fn=lambda d: NEAR)
    _, _, src = r.resolve("", *map(str, SUB))
    assert src == "submitted"
    assert r.stats["fetched"] == 0


def test_fetch_failure_degrades_to_submitted():
    def boom(url):
        raise RuntimeError("404")

    r = CoordResolver(fetch_bytes=boom)
    _, _, src = r.resolve("http://p/x.jpg", *map(str, SUB))
    assert src == "submitted"
    assert r.stats["fetch_fail"] == 1


def test_burnin_read_cached_once_per_photo():
    calls = []
    r = CoordResolver(
        fetch_bytes=_fetch(b"SAME"),
        exif_fn=lambda d: None,
        burnin_text_fn=lambda d, api_key=None: calls.append(1) or "UNSURE",
    )
    r.resolve("http://p/x.jpg", *map(str, SUB))
    r.resolve("http://p/x.jpg", *map(str, SUB))
    assert len(calls) == 1  # second call served from cache
    assert r.stats["llm_calls"] == 1


def test_llm_cap_skips_and_does_not_cache():
    calls = []
    r = CoordResolver(
        fetch_bytes=_fetch(b"SAME"),
        exif_fn=lambda d: None,
        burnin_text_fn=lambda d, api_key=None: calls.append(1) or "x",
        max_llm_calls=0,
    )
    r.resolve("http://p/x.jpg", *map(str, SUB))
    assert calls == []
    assert r.stats["llm_capped"] == 1
    assert r.cache == {}  # not cached -> a later run can still read it


def test_grok_api_key_forwarded():
    seen = {}

    def bt(data, api_key=None):
        seen["k"] = api_key
        return "UNSURE"

    r = CoordResolver(
        fetch_bytes=_fetch(),
        exif_fn=lambda d: None,
        burnin_text_fn=bt,
        grok_api_key="grok-key",
    )
    r.resolve("http://p/x.jpg", *map(str, SUB))
    assert seen["k"] == "grok-key"


# --- builder integration ----------------------------------------------------
def _row(msg_id, lat="-3.5229189", lng="-51.5749705", photo="http://p/x.jpg"):
    r = [""] * 22
    r[3], r[8], r[9], r[10], r[11], r[12] = msg_id, photo, "Farmer", lat, lng, "NEW"
    return r


def test_builder_without_resolver_passes_submitted_through():
    it = build_sunmint_pending([_row("E1")])["items"][0]
    assert it["latitude"] == "-3.5229189"
    assert it["longitude"] == "-51.5749705"
    assert it["coord_source"] == "submitted"


def test_builder_with_resolver_emits_resolved_and_source():
    resolver = CoordResolver(
        fetch_bytes=_fetch(),
        exif_fn=lambda d: None,
        burnin_text_fn=lambda d, api_key=None: "3.522803\u00b0S, 51.574812\u00b0W",
    )
    it = build_sunmint_pending([_row("E2")], None, resolver.resolve)["items"][0]
    assert it["coord_source"] == "burnin"
    assert it["latitude"] == "-3.522803"
    assert it["longitude"] == "-51.574812"


def test_builder_blank_both_coords_is_empty_source_without_resolver():
    it = build_sunmint_pending([_row("E3", lat="", lng="")])["items"][0]
    assert it["coord_source"] == ""
    assert it["latitude"] == ""
