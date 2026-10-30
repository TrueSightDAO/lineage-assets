"""Tests for the manifest -> pngs label reconciler.

The behaviour that matters is the DISTINCTION between a manifest that points at
a label which is absent (a broken public page) and a manifest that was never
asked to show a label at all (page falls back to the placeholder by design).
Collapsing those two would overstate the defect, so each is pinned separately.
"""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "qr_generator"))

import reconcile_labels as rl


def _write_manifest(
    manifest_dir, qr_id, url, asset_type="cacao_bag", status="MINTED", filename=None
):
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / (filename or f"{qr_id}.json")).write_text(
        json.dumps(
            {
                "qr_id": qr_id,
                "asset_type": asset_type,
                "status": status,
                "qr_image_url": url,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def stores(tmp_path):
    mdir, pdir = tmp_path / "qrs", tmp_path / "pngs"
    pdir.mkdir()
    return mdir, pdir


def _report(mdir, pdir, **kw):
    return rl.build_report(mdir, pdir, **kw)


def test_image_token_strips_dir_and_extension():
    assert rl.image_token("https://x/y/pngs/abc_1.png") == "abc_1"
    assert rl.image_token("https://x/y/pngs/abc%5F1.png") == "abc_1"
    assert rl.image_token("") == ""
    assert rl.image_token("https://x/y/pngs/abc_1") == "abc_1"


def test_manifest_pointing_at_absent_label_is_missing(stores):
    mdir, pdir = stores
    _write_manifest(mdir, "bag_1", "https://x/pngs/bag_1.png")
    (pdir / "other.png").write_bytes(b"x")

    report = _report(mdir, pdir)

    assert report["summary"]["missing_total"] == 1
    assert report["rows"][0]["qr_id"] == "bag_1"
    assert report["rows"][0]["state"] == "missing"


def test_present_label_is_not_reported_unless_include_ok(stores):
    mdir, pdir = stores
    _write_manifest(mdir, "bag_1", "https://x/pngs/bag_1.png")
    (pdir / "bag_1.png").write_bytes(b"x")

    assert _report(mdir, pdir)["rows"] == []
    assert len(_report(mdir, pdir, include_ok=True)["rows"]) == 1


def test_manifest_without_url_is_no_url_not_missing(stores):
    """A manifest never asked to show a label must NOT inflate the defect count."""
    mdir, pdir = stores
    _write_manifest(mdir, "legacy_1", "")

    report = _report(mdir, pdir)

    assert report["summary"]["missing_total"] == 0
    assert report["summary"]["no_url_total"] == 1


def test_asset_type_filter_scopes_the_report(stores):
    mdir, pdir = stores
    _write_manifest(mdir, "bag_1", "https://x/pngs/bag_1.png", asset_type="cacao_bag")
    _write_manifest(mdir, "pk_1", "https://x/pngs/pk_1.png", asset_type="tree")

    bag = _report(mdir, pdir, asset_type="cacao_bag")
    assert [r["qr_id"] for r in bag["rows"]] == ["bag_1"]
    assert bag["summary"]["missing_by_asset_type"] == {"cacao_bag": 1}


def test_exclude_pattern_skips_test_codes(stores):
    mdir, pdir = stores
    _write_manifest(mdir, "E2E_TEST_1", "https://x/pngs/E2E_TEST_1.png")
    _write_manifest(mdir, "2024_20260622_1", "https://x/pngs/2024_20260622_1.png")

    report = _report(mdir, pdir, exclude_pattern=r"^E2E")

    assert [r["qr_id"] for r in report["rows"]] == ["2024_20260622_1"]


def test_unreadable_manifest_does_not_abort_scan(stores, capsys):
    """One corrupt JSON must not hide every other label's status."""
    mdir, pdir = stores
    mdir.mkdir(parents=True)
    (mdir / "broken.json").write_text("{not json", encoding="utf-8")
    _write_manifest(mdir, "bag_1", "https://x/pngs/bag_1.png")

    report = _report(mdir, pdir)

    assert report["summary"]["missing_total"] == 1
    assert "broken.json" in capsys.readouterr().err


def test_non_dict_manifest_is_skipped(stores):
    mdir, pdir = stores
    mdir.mkdir(parents=True)
    (mdir / "list.json").write_text("[1,2,3]", encoding="utf-8")

    assert _report(mdir, pdir)["rows"] == []


def test_strict_exits_nonzero_only_when_something_missing(stores):
    mdir, pdir = stores
    _write_manifest(mdir, "bag_1", "https://x/pngs/bag_1.png")
    args = ["--manifest-dir", str(mdir), "--pngs-dir", str(pdir), "--strict"]

    assert rl.main(args) == 1
    (pdir / "bag_1.png").write_bytes(b"x")
    assert rl.main(args) == 0


def test_missing_store_path_fails_loudly(tmp_path):
    mdir = tmp_path / "qrs"
    mdir.mkdir()
    with pytest.raises(SystemExit):
        rl.build_report(mdir, tmp_path / "does_not_exist")
