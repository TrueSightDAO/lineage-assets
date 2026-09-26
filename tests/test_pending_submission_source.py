"""The public pending-cache must carry the submission ORIGIN so the dapp program
filter can narrow (e.g. only trees submitted via cfr.truesight.me -> crf-anapu).

The origin rides inside the "Contribution Made" cell (not a dedicated column):
an explicit "Submission Source: <value>" line, else the older
"This submission was generated using <url>" footer. Only a host/URL/sentinel may
surface -- the same cell carries a base64 signature blob which must never leak
into the public cache.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_pending_caches import (
    _load_registry,
    _resolve_program,
    _source_host,
    _submission_source,
    build_sunmint_pending,
)


def test_source_from_submission_source_line():
    txt = "[TREE PLANTING EVENT]\n- Latitude: -3.1\n- Submission Source: https://cfr.truesight.me/\n"
    assert _submission_source(txt) == "https://cfr.truesight.me/"


def test_source_falls_back_to_generated_using_footer():
    txt = (
        "[TREE PLANTING EVENT]\n- Latitude: 44.5\n--------\n\nMy Digital Signature: ABC\n\n"
        "This submission was generated using https://dapp.truesight.me/report_tree_planting.html?timestamp=1"
    )
    assert (
        _submission_source(txt)
        == "https://dapp.truesight.me/report_tree_planting.html?timestamp=1"
    )


def test_explicit_source_wins_over_footer():
    txt = "- Submission Source: autopilot-sophia\n...generated using https://github.com/TrueSightDAO/x"
    assert _submission_source(txt) == "autopilot-sophia"


def test_blank_and_markerless_are_empty():
    assert _submission_source("") == ""
    assert _submission_source("no marker in this cell") == ""


def test_signature_blob_never_leaks():
    txt = (
        "[TREE PLANTING EVENT]\nMy Digital Signature: MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n"
        "\nThis submission was generated using https://cfr.truesight.me/"
    )
    out = _submission_source(txt)
    assert out == "https://cfr.truesight.me/"
    assert "MIIB" not in out


def _row(msg_id, contribution, status="NEW"):
    """Build a SunMint-tab row (A..T) with the contribution cell (col F, idx 5)."""
    r = [""] * 20
    r[0], r[3], r[4], r[5], r[6] = "u1", msg_id, "garyjob", contribution, "20250711"
    r[8], r[9], r[10], r[11], r[12], r[13] = "photo", "Gary", "1", "2", status, "Cacao"
    return r


def test_build_pending_emits_submission_source():
    rows = [_row("Edgar_1", "- Submission Source: https://cfr.truesight.me/")]
    out = build_sunmint_pending(rows)
    assert out["count"] == 1
    assert out["items"][0]["submission_source"] == "https://cfr.truesight.me/"


def test_build_pending_blank_source_is_empty_string():
    rows = [_row("Edgar_2", "no marker")]
    out = build_sunmint_pending(rows)
    assert out["items"][0]["submission_source"] == ""


def test_non_new_rows_are_skipped():
    rows = [
        _row(
            "Edgar_3",
            "- Submission Source: https://cfr.truesight.me/",
            status="INVALID",
        )
    ]
    assert build_sunmint_pending(rows)["count"] == 0


# --- program resolution (Option B attribution) -----------------------------

_REG = {"cfr.truesight.me": "crf-anapu", "beta.cfr.truesight.me": "crf-anapu"}


def test_source_host_extracts_url_host():
    assert _source_host("https://cfr.truesight.me/") == "cfr.truesight.me"
    assert _source_host("https://cfr.truesight.me/x?y=1") == "cfr.truesight.me"


def test_source_host_passes_sentinel_through_lowercased():
    assert _source_host("autopilot-sophia") == "autopilot-sophia"
    assert _source_host("") == ""


def test_resolve_program_matches_registered_host():
    assert _resolve_program("https://cfr.truesight.me/", _REG) == "crf-anapu"
    assert _resolve_program("https://beta.cfr.truesight.me/", _REG) == "crf-anapu"


def test_resolve_program_empty_for_unregistered():
    # Gary's rule: no explicit program association -> EMPTY, so it shows under none.
    assert _resolve_program("autopilot-sophia", _REG) == ""
    assert _resolve_program("https://localhost/", _REG) == ""
    assert _resolve_program("", _REG) == ""
    assert _resolve_program("https://cfr.truesight.me/", {}) == ""


def test_load_registry_normalises_hosts():
    assert _load_registry({"hosts": {"CFR.TrueSight.ME": "crf-anapu"}}) == {
        "cfr.truesight.me": "crf-anapu"
    }
    assert _load_registry(None) == {}


def _rows_with_source(src):
    # Minimal row: cols are 0-based per COL (3=msg_id, 5=source, 9=name, 12=status)
    r = [""] * 18
    r[3] = "12345"
    r[5] = src
    r[9] = "Farmer"
    r[12] = "NEW"
    return [r]


def test_builder_emits_resolved_program():
    it = build_sunmint_pending(
        _rows_with_source("Submission Source: https://cfr.truesight.me/"), _REG
    )["items"][0]
    assert it["program"] == "crf-anapu"


def test_builder_program_empty_when_unattributable():
    it = build_sunmint_pending(
        _rows_with_source("Submission Source: autopilot-sophia"), _REG
    )["items"][0]
    assert it["program"] == ""
    assert it["submission_source"] == "autopilot-sophia"


def test_builder_still_works_without_registry():
    it = build_sunmint_pending(
        _rows_with_source("Submission Source: https://cfr.truesight.me/")
    )["items"][0]
    assert it["program"] == ""  # no registry -> nothing resolves
