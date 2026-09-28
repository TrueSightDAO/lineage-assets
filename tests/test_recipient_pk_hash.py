"""The public pending cache must carry each tree's recipient `pk_hash` so the dapp
can autofill the payout recipient WITHOUT a GAS call (Gary, 2026-09-28, thread 35944).

The GAS `getTreeRecipientMap` read shares ONE Apps Script deployment with
`getPendingPayoutRegistrations`, so the platform serialises them and the map can
answer ~9-10s late -- which is what made the payout field look broken. Reading the
value from this cache removes that call from the page-load critical path.

`pk_hash` is the ONE-WAY signer identity and is PUBLIC by design
(conventions/DEDUP_KEY_CONVENTION.md SS2.6) -- the same opaque `pk-...` value
already published in lineage-assets/qrs_index.json. Raw PII (PIX/CPF/email/phone)
is never emitted.

Join: the private `tree planting` tab is the only place a `tree_id` and its
`pk_hash` co-exist; the map is read first-row-wins per tree_id.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_pending_caches import build_sunmint_pending, build_tree_recipient_map

HEADER = ["created_at_utc", "telegram_update_id", "pk_hash", "tree_id", "species"]


def _sunmint_row(msg_id: str) -> list:
    """A minimal SunMint-tab row: col D (idx 3) msg id, col M (idx 12) status."""
    row = [""] * 22
    row[3] = msg_id
    row[12] = "NEW"
    return row


def test_map_pairs_tree_id_to_pk_hash():
    rows = [
        HEADER,
        ["t", "u1", "pk-aaa", "Edgar_X_1", "Cacao"],
        ["t", "u2", "pk-bbb", "Edgar_X_2", "Cacao"],
    ]
    assert build_tree_recipient_map(rows) == {
        "Edgar_X_1": "pk-aaa",
        "Edgar_X_2": "pk-bbb",
    }


def test_map_first_row_wins_per_tree_id():
    rows = [
        HEADER,
        ["t", "u1", "pk-first", "Edgar_X_1", "Cacao"],
        ["t", "u2", "pk-second", "Edgar_X_1", "Cacao"],
    ]
    assert build_tree_recipient_map(rows) == {"Edgar_X_1": "pk-first"}


def test_map_is_blank_on_missing_columns_or_blank_cells():
    assert build_tree_recipient_map([]) == {}
    assert build_tree_recipient_map([["foo", "bar"]]) == {}
    rows = [
        HEADER,
        ["t", "u1", "", "Edgar_X_1", "Cacao"],
        ["t", "u2", "pk-bbb", "", "Cacao"],
    ]
    assert build_tree_recipient_map(rows) == {}


def test_pending_item_carries_recipient_pk_hash():
    out = build_sunmint_pending(
        [_sunmint_row("Edgar_X_1")], recipient_map={"Edgar_X_1": "pk-aaa"}
    )
    assert out["items"][0]["recipient_pk_hash"] == "pk-aaa"


def test_pending_item_recipient_blank_when_unregistered():
    out = build_sunmint_pending(
        [_sunmint_row("Edgar_X_2")], recipient_map={"Edgar_X_1": "pk-aaa"}
    )
    assert out["items"][0]["recipient_pk_hash"] == ""


def test_pending_recipient_defaults_to_empty_without_a_map():
    out = build_sunmint_pending([_sunmint_row("Edgar_X_3")])
    assert out["items"][0]["recipient_pk_hash"] == ""


def test_no_raw_pii_key_leaks_onto_an_item():
    out = build_sunmint_pending(
        [_sunmint_row("Edgar_X_1")], recipient_map={"Edgar_X_1": "pk-aaa"}
    )
    item = out["items"][0]
    for banned in ("pix_key", "cpf", "email", "phone"):
        assert not any(banned in k.lower() for k in item), banned
