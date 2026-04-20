"""Layer D — malformed bodies + signature bit flips → 4xx, never 500."""
from __future__ import annotations

import os

import httpx


def test_D_chaos__random_garbage_bodies_never_500(
    client: httpx.Client, make_event,
) -> None:
    for _ in range(20):
        garbage = os.urandom(64)
        r = client.post(
            "/webhook", content=garbage,
            headers={"X-Signature": "deadbeef" * 8, "content-type": "application/octet-stream"},
        )
        assert r.status_code < 500, f"500 on garbage: {r.text[:200]}"
        assert r.status_code in (400, 401, 415, 422), f"expected 4xx, got {r.status_code}"


def test_D_chaos__bit_flipped_signature_rejected(
    client: httpx.Client, make_event,
) -> None:
    raw, headers = make_event()
    sig = headers["X-Signature"]
    # Flip one hex char.
    flipped = (("1" if sig[0] != "1" else "2") + sig[1:])
    headers["X-Signature"] = flipped
    r = client.post("/webhook", content=raw, headers=headers)
    assert r.status_code == 401, f"bit-flipped sig must 401, got {r.status_code}"
