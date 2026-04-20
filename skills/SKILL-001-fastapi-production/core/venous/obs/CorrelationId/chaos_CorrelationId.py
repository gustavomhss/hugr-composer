"""Chaos / fault-injection for CorrelationId."""

from __future__ import annotations

import threading

import pytest

from CorrelationId import (
    CorrelationIdError,
    StatelessCorrelationIdProvider,
    extract,
    generate,
    inject,
    parse,
)


def test_chaos_malformed_upstream_headers_never_crash() -> None:
    for bad in (
        {"x-request-id": ""},
        {"x-request-id": "short"},
        {"x-request-id": "!!!@@@###"},
        {"traceparent": "not-a-traceparent"},
        {"traceparent": "00-" + "z" * 32 + "-" + "z" * 16 + "-01"},
        {},
    ):
        cid = extract(bad)
        assert len(cid) >= 16


def test_chaos_parse_rejects_all_invalid_shapes() -> None:
    for bad in ("", "short", "NOTHEX__________", "!!!@@@###", "a" * 15, "a" * 65):
        with pytest.raises(CorrelationIdError):
            parse(bad)


def test_chaos_concurrent_generate_no_collisions() -> None:
    # 8 threads × 500 ids each — CSPRNG must not collide under contention.
    produced: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        batch = [generate() for _ in range(500)]
        with lock:
            produced.extend(batch)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(produced) == 4000
    assert len(set(produced)) == 4000


def test_chaos_inject_cannot_leak_non_string_id() -> None:
    # A caller bypassing NewType and passing a non-str MUST be rejected
    # before any outbound header is synthesised.
    with pytest.raises(CorrelationIdError):
        inject(12345)  # type: ignore[arg-type]  — CORRID-INV-05 defence.


def test_chaos_repeated_extract_of_same_header_is_deterministic() -> None:
    headers = {"x-request-id": "feedfacefeedfacefeedfacefeedface"}
    ids = {extract(headers) for _ in range(100)}
    assert ids == {"feedfacefeedfacefeedfacefeedface"}


def test_chaos_provider_under_load_yields_unique_ids() -> None:
    provider = StatelessCorrelationIdProvider()
    seen: set[str] = set()
    for _ in range(2000):
        seen.add(provider.current())
    assert len(seen) == 2000


def test_chaos_header_injection_via_crlf_rejected() -> None:
    # A malicious upstream header embedding CRLF MUST NOT leak into parse().
    with pytest.raises(CorrelationIdError):
        parse("deadbeefdeadbeef\r\nSet-Cookie: x=1")
