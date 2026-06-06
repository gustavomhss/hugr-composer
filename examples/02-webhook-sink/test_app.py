"""Tests for the webhook-sink example."""
from __future__ import annotations

import hashlib
import hmac
import threading

import pytest

from app import IdempotentInbox, SignatureError, verify_signature


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_bad_signature_raises() -> None:
    with pytest.raises(SignatureError):
        verify_signature(
            secret=b"k", body=b"x", signature_header="00" * 32,
            timestamp=1_000_000, now=1_000_000,
        )


def test_timestamp_outside_window_raises() -> None:
    body, secret = b"x", b"k"
    with pytest.raises(SignatureError, match="timestamp"):
        verify_signature(
            secret=secret, body=body, signature_header=_sign(body, secret),
            timestamp=1_000_000, now=1_000_000 + 301, tolerance_s=300,
        )


def test_good_signature_passes() -> None:
    body, secret = b"hello", b"key"
    verify_signature(
        secret=secret, body=body, signature_header=_sign(body, secret),
        timestamp=1_000_000, now=1_000_000 + 5,
    )


def test_exactly_once_under_ten_parallel_duplicates() -> None:
    inbox = IdempotentInbox()
    results: list = []
    lock = threading.Lock()

    def worker() -> None:
        r = inbox.process(provider="stripe", event_id="evt_42", body=b"{}", verified=True)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
    assert len(losers) == 9
    assert len(inbox.all_accepted()) == 1


def test_distinct_event_ids_all_accepted() -> None:
    inbox = IdempotentInbox()
    for i in range(5):
        assert inbox.process(provider="stripe", event_id=f"e{i}", body=b"", verified=True) is not None
    assert len(inbox.all_accepted()) == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
