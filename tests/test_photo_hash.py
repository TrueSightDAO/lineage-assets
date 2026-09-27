"""Perceptual (dHash) duplicate safety net for the public pending cache."""

import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from photo_hash import PHASH_BITS, dhash_hex, hamming_hex

try:
    from PIL import Image

    _HAVE_PIL = True
except ImportError:  # pragma: no cover - Pillow is a declared dependency
    _HAVE_PIL = False


def _img_bytes(seed: int, size=(64, 64)) -> bytes:
    """Deterministic smooth image; the pattern (hence dHash) depends on ``seed``."""
    im = Image.new("L", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            v = 128 + 100 * math.sin((x + seed * 11) / 6.0) * math.cos(
                (y + seed * 5) / 7.0
            )
            px[x, y] = max(0, min(255, int(v)))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_hamming_hex_basic_and_guards():
    assert hamming_hex("0", "0") == 0
    assert hamming_hex("f", "0") == 4
    assert hamming_hex("", "0") == 10**9
    assert hamming_hex("0", "00") == 10**9
    assert hamming_hex("zz", "00") == 10**9


def test_dhash_hex_shape_and_stability():
    if not _HAVE_PIL:
        return
    h = dhash_hex(_img_bytes(1))
    assert len(h) == PHASH_BITS // 4 == 16
    assert all(c in "0123456789abcdef" for c in h)
    assert dhash_hex(_img_bytes(1)) == h  # deterministic


def test_dhash_same_photo_reencoded_is_within_gate():
    if not _HAVE_PIL:
        return
    # A JPEG re-encode of the same picture must stay inside the <=8 duplicate gate.
    im = Image.open(io.BytesIO(_img_bytes(3)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=70)
    d = hamming_hex(dhash_hex(_img_bytes(3)), dhash_hex(buf.getvalue()))
    assert d <= 8, d


def test_dhash_different_photos_exceed_gate():
    if not _HAVE_PIL:
        return
    d = hamming_hex(dhash_hex(_img_bytes(1)), dhash_hex(_img_bytes(5)))
    assert d > 8, d


def test_dhash_empty_and_garbage_are_blank():
    assert dhash_hex(b"") == ""
    assert dhash_hex(b"not an image at all") == ""
