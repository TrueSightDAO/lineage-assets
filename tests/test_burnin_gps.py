"""Burn-in GPS reader: Grok-only, guarded, cache-once.

Pins the governor directive (Gary, 2026-09-27) that burn-in extraction uses Grok
(not Claude) and that an unreadable reading degrades to None -- never a guess.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from burnin_gps import (
    GROK_ENDPOINT,
    PROMPT,
    burnin_gps,
    cache_key,
    load_cache,
    read_burnin_text,
    save_cache,
)


def _resp(content):
    return {"choices": [{"message": {"content": content}}]}


def _transport(content):
    calls = []

    def t(url, headers, payload):
        calls.append((url, headers, payload))
        return _resp(content)

    t.calls = calls
    return t


def test_prompt_is_grok_native_endpoint():
    assert GROK_ENDPOINT.startswith("https://api.x.ai/")


def test_prompt_forbids_guessing():
    assert "UNSURE" in PROMPT
    assert "not guess" in PROMPT.lower()


def test_read_burnin_text_parses_grok_response():
    t = _transport("3.522803S, 51.574812W")
    out = read_burnin_text(b"x", api_key="k", transport=t)
    assert out == "3.522803S, 51.574812W"
    # went to the x.ai endpoint with a bearer token
    url, headers, _ = t.calls[0]
    assert url == GROK_ENDPOINT
    assert headers["Authorization"] == "Bearer k"


def test_payload_is_openai_image_shape():
    t = _transport("3.522803S, 51.574812W")
    read_burnin_text(b"x", api_key="k", transport=t)
    _, _, payload = t.calls[0]
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_burnin_gps_returns_tuple():
    t = _transport("3.522803S, 51.574812W")
    lat, lng = burnin_gps(b"x", api_key="k", transport=t)
    assert lat == pytest.approx(-3.522803)
    assert lng == pytest.approx(-51.574812)


def test_unsure_yields_none():
    t = _transport("UNSURE")
    assert burnin_gps(b"x", api_key="k", transport=t) is None


def test_non_gps_text_yields_none():
    t = _transport("Anapu - PA, 68365-000")
    assert burnin_gps(b"x", api_key="k", transport=t) is None


def test_missing_api_key_and_photo_return_empty():
    assert read_burnin_text(b"x", api_key="", transport=_transport("z")) == ""
    assert read_burnin_text(b"", api_key="k", transport=_transport("z")) == ""


def test_transport_error_degrades_to_empty():
    def boom(url, headers, payload):
        raise RuntimeError("network down")

    assert read_burnin_text(b"x", api_key="k", transport=boom) == ""
    assert burnin_gps(b"x", api_key="k", transport=boom) is None


def test_malformed_response_degrades_to_empty():
    assert read_burnin_text(b"x", api_key="k", transport=lambda *a: {}) == ""


def test_cache_key_stable_and_content_addressed():
    assert cache_key(b"abc") == cache_key(b"abc")
    assert cache_key(b"abc") != cache_key(b"abd")
    assert len(cache_key(b"abc")) == 64


def test_cache_roundtrip(tmp_path):
    p = tmp_path / "burnin_cache.json"
    assert load_cache(str(p)) == {}
    save_cache(str(p), {"deadbeef": "3.522803S, 51.574812W"})
    assert load_cache(str(p)) == {"deadbeef": "3.522803S, 51.574812W"}


def test_load_cache_corrupt_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_cache(str(p)) == {}
