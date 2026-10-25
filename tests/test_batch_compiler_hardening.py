"""
Regression tests for the three hardening checks added 2026-10-25 after the
Vivi 81% bar 50g (AGL13) QR batch incident: wrong-logo selection, duplicate
ids, and a missing branding self-check. See
AGROVERSE_QR_CODE_BATCH_GENERATION.md for the SOP these enforce.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "qr_generator"))

from batch_compiler import (  # noqa: E402
    resolve_is_cacao,
    find_duplicate_qr_codes,
    scope_rows,
    _assert_branded,
)


class TestResolveIsCacao:
    def test_no_www_prefix_is_still_cacao(self):
        # The real bug: sheet rows never carry "www." — this must resolve True.
        assert resolve_is_cacao("https://agroverse.shop/shipments/agl13/index.html") is True

    def test_www_prefix_is_cacao(self):
        assert resolve_is_cacao("https://www.agroverse.shop/product-page/x/") is True

    def test_unrelated_domain_is_not_cacao(self):
        assert resolve_is_cacao("https://truesight.me/qr/?id=x") is False

    def test_lookalike_domain_is_not_cacao(self):
        # agroverse.shop.evil.example must NOT match via a naive substring/startswith check.
        assert resolve_is_cacao("https://agroverse.shop.evil.example/x") is False

    def test_empty_url_is_not_cacao(self):
        assert resolve_is_cacao("") is False


class TestFindDuplicateQrCodes:
    def _row(self, qr_code):
        return ((qr_code, "Farm", "State", "Country", "2025", True), [qr_code])

    def test_no_duplicates(self):
        rows = [self._row("A_1"), self._row("A_2"), self._row("A_3")]
        assert find_duplicate_qr_codes(rows) == {}

    def test_detects_duplicates_with_counts(self):
        rows = [self._row("A_1"), self._row("A_2"), self._row("A_1"), self._row("A_2")]
        assert find_duplicate_qr_codes(rows) == {"A_1": 2, "A_2": 2}

    def test_matches_the_real_incident_shape(self):
        # 107 rows, 100 unique, 7 duplicated — the actual Vivi batch state.
        base = [self._row(f"V_{i}") for i in range(1, 101)]
        dupes = [self._row(f"V_{i}") for i in (63, 84, 85, 86, 117, 118, 120) if i <= 100]
        # emulate with ids that exist in base (first 7 for simplicity)
        dupes = [self._row(f"V_{i}") for i in range(1, 8)]
        rows = base + dupes
        result = find_duplicate_qr_codes(rows)
        assert len(result) == 7
        assert all(n == 2 for n in result.values())


class TestAssertBranded:
    def _bare_qr_image(self):
        # Exactly 2 grayscale values, like a raw QR render with no logo.
        img = Image.new("RGB", (100, 100), "white")
        px = img.load()
        for x in range(0, 100, 2):
            for y in range(100):
                px[x, y] = (0, 0, 0)
        return img

    def _branded_image(self):
        # Many distinct grayscale values, like a composited logo + AA text.
        img = Image.new("RGB", (100, 100), "white")
        px = img.load()
        for x in range(100):
            for y in range(100):
                v = (x * 7 + y * 13) % 256
                px[x, y] = (v, v, v)
        return img

    def test_bare_qr_raises(self):
        with pytest.raises(AssertionError, match="bare QR"):
            _assert_branded(self._bare_qr_image(), "TEST_1", "some_logo.png")

    def test_branded_image_passes(self):
        _assert_branded(self._branded_image(), "TEST_1", "some_logo.png")  # no raise

    def test_no_logo_flag_bypasses_check(self):
        # --no-logo runs legitimately produce a bare QR; must not false-positive.
        _assert_branded(self._bare_qr_image(), "TEST_1", None, no_logo=True)  # no raise

    def test_missing_logo_path_bypasses_check(self):
        _assert_branded(self._bare_qr_image(), "TEST_1", None, no_logo=False)  # no raise


class TestGuardScopedToSelectedRows:
    """The duplicate-id guard must judge the rows a run will actually mint.

    Regression: the guard originally ran BEFORE the --qr / --only-missing-png
    filters and therefore scanned the entire sheet, so a duplicate anywhere made
    every targeted run impossible. That is not hypothetical -- it made the
    on-demand "Generate QR label PNGs" workflow abort with 0 files produced
    while 7 unrelated duplicates sat in the sheet (2026-10-25, Vivi AGL13).
    """

    def _row(self, qr_code):
        return ((qr_code, "Farm", "State", "Country", "2025", True), [qr_code])

    def test_targeted_selection_excludes_unrelated_duplicates(self):
        # Sheet has a dup in _63, but we only asked for _1.
        rows = [self._row("_1"), self._row("_63"), self._row("_63")]
        selected, _ = scope_rows(rows, ["_1"])
        assert [r[0][0] for r in selected] == ["_1"]
        # The guard therefore sees no duplicates and does not abort.
        assert find_duplicate_qr_codes(selected) == {}

    def test_selection_naming_a_duplicated_id_still_aborts(self):
        rows = [self._row("_1"), self._row("_63"), self._row("_63")]
        selected, _ = scope_rows(rows, ["_63"])
        assert find_duplicate_qr_codes(selected) == {"_63": 2}

    def test_full_selection_still_sees_corpus_duplicates(self):
        # No filters -> every row selected -> corpus-wide detection unchanged.
        rows = [self._row("_1"), self._row("_63"), self._row("_63")]
        selected, _ = scope_rows(rows, None)
        assert find_duplicate_qr_codes(selected) == {"_63": 2}

    def test_missing_png_filter_scoped_before_guard(self, tmp_path):
        rows = [self._row("_1"), self._row("_63"), self._row("_63")]
        (tmp_path / "_1.png").write_bytes(b"x")
        selected, notes = scope_rows(rows, None, True, str(tmp_path))
        # _1 already has a PNG, so only the _63 pair survives -> still a dup.
        assert [r[0][0] for r in selected] == ["_63", "_63"]
        assert find_duplicate_qr_codes(selected) == {"_63": 2}
        assert any("only-missing-png" in n for n in notes)

    def test_scope_rows_reports_unknown_ids(self):
        rows = [self._row("_1")]
        selected, notes = scope_rows(rows, ["_1", "_999"])
        assert [r[0][0] for r in selected] == ["_1"]
        assert any("NOT IN SHEET" in n and "_999" in n for n in notes)
