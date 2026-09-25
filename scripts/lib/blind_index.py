"""Peppered blind index for owner emails.

A blind index answers "which bags belong to this email?" WITHOUT ever storing
or publishing the email, and WITHOUT a plain hash that a small candidate list
could brute-force.

    token = HMAC_SHA256(pepper, normalize(email))[:16]   # 16 hex chars = 64 bits

- ``normalize()`` lowercases + strips, so the same address always maps to the
  same token.
- The pepper is a SECRET (env ``OWNER_EMAIL_PEPPER``). It is NEVER committed and
  NEVER written into any JSON -- it lives only in the box env / deploy secret
  store. Without it the token reveals nothing.
- FAIL CLOSED: with no pepper configured ``compute_owner_email_hash`` returns
  None, so nothing is published. An unpeppered hash would be reversible by
  guessing common emails, which is exactly what must not happen.

Rotating the pepper invalidates every previously published token (all lookups
break) -- treat it as a key ceremony, not a config tweak.
"""
from __future__ import annotations

import hashlib
import hmac
import os

PEPPER_ENV = "OWNER_EMAIL_PEPPER"
TOKEN_HEX_LEN = 16  # 64 bits -- collision-safe at our scale, keeps JSON small


def normalize(email: str) -> str:
    """Canonicalise an email so equal addresses map to equal tokens."""
    return (email or "").strip().lower()


def _pepper(explicit: str | None = None) -> bytes | None:
    val = explicit if explicit is not None else os.environ.get(PEPPER_ENV, "")
    val = (val or "").strip()
    return val.encode("utf-8") if val else None


def compute_owner_email_hash(email: str, pepper: str | None = None) -> str | None:
    """Return the peppered blind-index token for ``email``, or None.

    Returns None when the email is empty OR no pepper is configured (fail
    closed -- never emit an unpeppered/reversible token).
    """
    if not normalize(email):
        return None
    key = _pepper(pepper)
    if not key:
        return None
    digest = hmac.new(key, normalize(email).encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:TOKEN_HEX_LEN]
