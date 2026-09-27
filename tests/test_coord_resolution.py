"""Coordinate resolution: EXIF > burn-in > submitted, with a sanity guard.

Encodes governor-approved priority (Gary, 2026-09-27) and pins the guard that
rejects a hallucinated round-number burn-in reading.
"""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from coord_resolution import (
    _gps_from_ifd,
    exif_gps,
    format_coord,
    haversine_m,
    parse_gps_text,
    resolve_coordinates,
)

# A 1x1 PNG with no EXIF (smallest possible "photo" fixture).
_PNG_NO_EXIF = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_parse_decimal_south_west():
    assert parse_gps_text("3.522803\u00b0S, 51.574812\u00b0W") == pytest.approx(
        (-3.522803, -51.574812)
    )


def test_parse_decimal_north_east():
    lat, lng = parse_gps_text("44.500000\u00b0N 1.200000\u00b0E")
    assert lat == pytest.approx(44.5)
    assert lng == pytest.approx(1.2)


def test_parse_dms():
    lat, lng = parse_gps_text("3\u00b0 31' 22.09\" S  51\u00b0 34' 29.32\" W")
    assert lat == pytest.approx(-3.522803, abs=1e-5)
    assert lng == pytest.approx(-51.574811, abs=1e-5)


def test_parse_absent_or_non_gps():
    assert parse_gps_text("") is None
    assert parse_gps_text("Anapu - PA, 68365-000") is None
    assert parse_gps_text("Qui, 24 set. 2026 10:16") is None


def test_exif_absent():
    assert exif_gps(b"") is None
    assert exif_gps(_PNG_NO_EXIF) is None


def test_gps_from_ifd():
    ifd = {1: "S", 2: (3, 31, 22.09), 3: "W", 4: (51, 34, 29.32)}
    lat, lng = _gps_from_ifd(ifd)
    assert lat == pytest.approx(-3.522803, abs=1e-5)
    assert lng == pytest.approx(-51.574811, abs=1e-5)


def test_gps_from_ifd_empty():
    assert _gps_from_ifd({}) is None
    assert _gps_from_ifd(None) is None


def test_haversine_known_scale():
    # ~111 m per 0.001 deg of latitude near the equator.
    assert haversine_m((0, 0), (0.001, 0)) == pytest.approx(111.19, abs=1.0)


def test_resolve_exif_wins_over_burnin():
    _, _, src = resolve_coordinates(
        exif=(-3.52280, -51.57480),
        burnin_text="3.522803\u00b0S, 51.574812\u00b0W",
        submitted=(-3.5229189, -51.5749705),
    )
    assert src == "exif"


def test_resolve_burnin_when_no_exif():
    lat, _, src = resolve_coordinates(
        burnin_text="3.522803\u00b0S, 51.574812\u00b0W",
        submitted=(-3.5229189, -51.5749705),
    )
    assert src == "burnin"
    assert lat == pytest.approx(-3.522803, abs=1e-5)


def test_resolve_rejects_hallucinated_round_burnin():
    # Round placeholder ~thousands of km off -> must fall back to submitted.
    lat, _, src = resolve_coordinates(
        burnin_text="04\u00b0 04' 04\" S  55\u00b0 55' 55\" W",
        submitted=(-3.5229189, -51.5749705),
    )
    assert src == "submitted"
    assert lat == pytest.approx(-3.5229189)


def test_resolve_rejects_far_exif():
    _, _, src = resolve_coordinates(
        exif=(44.5, 1.2), submitted=(-3.5229189, -51.5749705)
    )
    assert src == "submitted"


def test_resolve_no_submitted_accepts_exif():
    _, _, src = resolve_coordinates(exif=(-3.52280, -51.57480), submitted=None)
    assert src == "exif"


def test_resolve_all_absent():
    assert resolve_coordinates() == (None, None, "")


def test_format_coord():
    assert format_coord(-3.522803) == "-3.522803"
    assert format_coord(None) == ""
