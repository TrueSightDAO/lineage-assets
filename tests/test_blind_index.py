import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib.blind_index import compute_owner_email_hash, normalize  # noqa: E402


def test_normalize():
    assert normalize("  Gary@Truesight.me ") == "gary@truesight.me"
    assert normalize("") == ""
    assert normalize(None) == ""


def test_fail_closed_without_pepper(monkeypatch):
    monkeypatch.delenv("OWNER_EMAIL_PEPPER", raising=False)
    assert compute_owner_email_hash("a@b.com") is None


def test_empty_email_is_none(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_PEPPER", "p")
    assert compute_owner_email_hash("") is None
    assert compute_owner_email_hash("   ") is None


def test_deterministic_and_normalized(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_PEPPER", "p")
    a = compute_owner_email_hash("Gary@Truesight.me ")
    b = compute_owner_email_hash("gary@truesight.me")
    assert a == b
    assert a is not None and len(a) == 16


def test_pepper_changes_token():
    assert compute_owner_email_hash("x@y.com", pepper="p1") == \
        compute_owner_email_hash("x@y.com", pepper="p1")
    assert compute_owner_email_hash("x@y.com", pepper="p1") != \
        compute_owner_email_hash("x@y.com", pepper="p2")


def test_distinct_emails_distinct_tokens(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL_PEPPER", "p")
    assert compute_owner_email_hash("a@b.com") != compute_owner_email_hash("c@d.com")
