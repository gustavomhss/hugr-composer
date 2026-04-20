"""Behavioral scenarios for CorrelationId — end-to-end propagation."""

from __future__ import annotations

import re

from CorrelationId import extract, generate, inject, parse, to_str

_HEX = re.compile(r"^[0-9a-f]{16,64}$")


def test_scenario_ingress_propagation_end_to_end() -> None:
    # Service A mints an id, Service B sees it via x-request-id.
    a_cid = generate()
    outbound = inject(a_cid)
    b_cid = extract(outbound)
    assert b_cid == a_cid


def test_scenario_cold_request_no_upstream_headers() -> None:
    # A scheduled job has no inbound headers — extract() still produces a
    # valid id before any log line is emitted.
    cid = extract({})
    assert _HEX.match(cid)


def test_scenario_traceparent_fallback_preserves_trace_id() -> None:
    # Upstream only sent traceparent — the 32-char trace segment is reused.
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    cid = extract({"traceparent": tp})
    assert cid == "4bf92f3577b34da6a3ce929d0e0e4736"
    # It must round-trip cleanly through inject / extract.
    forwarded = extract(inject(cid))
    assert forwarded == cid


def test_scenario_outbound_enrichment_preserves_caller_headers() -> None:
    cid = generate()
    caller = {"content-type": "application/json", "authorization": "Bearer tok"}
    out = inject(cid, caller)
    # Caller headers survive, x-request-id is added, nothing is mutated.
    assert out["content-type"] == "application/json"
    assert out["authorization"] == "Bearer tok"
    assert out["x-request-id"] == cid


def test_scenario_log_binding_is_stable_across_hops() -> None:
    # Logger "binds" the id at ingress; subsequent hops must observe the
    # same id so queries can join log lines across services.
    ingress_cid = extract({"x-request-id": "abcdef0123456789abcdef0123456789"})
    log_values = [to_str(ingress_cid) for _ in range(5)]
    assert set(log_values) == {"abcdef0123456789abcdef0123456789"}


def test_scenario_parse_then_inject_is_lossless() -> None:
    raw = "0123456789abcdef" * 2  # exactly 32 lowercase hex chars.
    cid = parse(raw)
    out = inject(cid)
    assert out["x-request-id"] == raw
