"""Metamorphic + differential tests for CorrelationId."""

from __future__ import annotations

from CorrelationId import extract, generate, inject, parse, to_str


def test_metamorphic_inject_extract_roundtrip() -> None:
    cid = generate()
    assert extract(inject(cid)) == cid


def test_metamorphic_case_insensitive_inbound_header() -> None:
    upstream = "0123456789abcdef0123456789abcdef"
    for key in ("x-request-id", "X-Request-Id", "X-REQUEST-ID"):
        assert extract({key: upstream}) == upstream


def test_metamorphic_uppercase_hex_normalised() -> None:
    upstream = "DEADBEEFCAFEBABE0123456789ABCDEF"
    assert extract({"x-request-id": upstream}) == upstream.lower()


def test_metamorphic_parse_to_str_identity() -> None:
    raw = "abcdefabcdefabcdef1234567890feed"
    assert to_str(parse(raw)) == raw


def test_differential_all_ids_distinct_across_1000_calls() -> None:
    ids = {generate() for _ in range(1000)}
    assert len(ids) == 1000


def test_metamorphic_inject_is_pure_function() -> None:
    cid = generate()
    base = {"x-trace-flags": "01"}
    a = inject(cid, base)
    b = inject(cid, base)
    assert a == b
    # Caller mapping untouched.
    assert base == {"x-trace-flags": "01"}


def test_metamorphic_priority_x_request_id_over_traceparent() -> None:
    req = "cafebabecafebabecafebabecafebabe"
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    cid = extract({"x-request-id": req, "traceparent": tp})
    assert cid == req
