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

from sync_pending_caches import _submission_source, build_sunmint_pending


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
