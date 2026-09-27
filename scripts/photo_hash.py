"""Perceptual (difference) hash of a tree-planting photo -- the duplicate safety net.

The public pending cache lets the dapp flag two rows whose ``photo_url`` is
byte-identical. That misses the SAME physical photo re-ingested under a NEW url (a
re-upload, a different CDN path, a mirror re-run). A perceptual hash survives
re-encoding, so a pair whose hashes sit within a small Hamming distance is the same
picture even when the urls differ.

``dhash_hex`` returns a 64-bit difference hash (``hash_size=8`` -> 8x8 gradient
bits) as 16 lowercase hex chars, using Pillow only (no imagehash/numpy dependency;
Pillow is already required).

Empirical gate (live feed, 137 distinct rows, 2026-09-27): the closest pair of
DIFFERENT-url photos is 15/64 bits apart, while every <=8 pair shares a url. The
dapp's ``OVERPAY_PHASH_HAMMING = 8`` threshold therefore never merges two genuinely
different trees.
"""

from __future__ import annotations

import io

PHASH_BITS = 64
_DHASH_HEX_LEN = 16  # 64 bits / 4 bits per hex char
_NONMATCH = 10**9


def hamming_hex(a: str, b: str) -> int:
    """Number of differing bits between two equal-length hex strings.

    Returns ``_NONMATCH`` (a large sentinel) for blank / unequal-length / non-hex
    input so callers read it as "not a match".
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or len(a) != len(b):
        return _NONMATCH
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except ValueError:
        return _NONMATCH


def dhash_hex(image_bytes: bytes) -> str:
    """64-bit difference hash of ``image_bytes`` as 16 lowercase hex chars.

    ``""`` when the image can't be decoded or Pillow isn't installed -- callers treat
    an empty hash as "no comparison available" (fail-open, never a wrong merge).
    """
    if not image_bytes:
        return ""
    try:
        from PIL import Image
    except ImportError:  # noqa: BLE001 - Pillow optional; no hash rather than a crash
        return ""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:  # Pillow < 9.1
                resample = Image.LANCZOS
            grey = im.convert("L").resize((9, 8), resample)
            px = grey.tobytes()  # 9x8 grayscale -> 72 bytes, directly indexable
    except Exception:  # noqa: BLE001 - undecodable image => no hash
        return ""
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] < px[base + col + 1] else 0)
    return format(bits, f"0{_DHASH_HEX_LEN}x")
