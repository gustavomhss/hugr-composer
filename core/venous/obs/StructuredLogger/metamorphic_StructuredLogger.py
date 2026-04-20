"""Metamorphic + differential for StructuredLogger."""

from __future__ import annotations

import json

from StructuredLogger import InMemoryStructuredLogger


def test_metamorphic_json_roundtrip() -> None:
    log = InMemoryStructuredLogger()
    log.info("roundtrip", a=1, b="two", c=True)
    rec = json.loads(log.records[0])
    # The deserialised dict is a superset of the caller-provided fields.
    assert rec["a"] == 1 and rec["b"] == "two" and rec["c"] is True


def test_metamorphic_bind_is_associative() -> None:
    parent = InMemoryStructuredLogger()
    a_then_b = parent.bind(a=1).bind(b=2)
    b_then_a = parent.bind(b=2).bind(a=1)
    a_then_b.info("x")
    b_then_a.info("x")
    rec1 = json.loads(a_then_b.records[0])
    rec2 = json.loads(b_then_a.records[0])
    assert rec1["a"] == rec2["a"] == 1
    assert rec1["b"] == rec2["b"] == 2


def test_metamorphic_record_ordering_preserved() -> None:
    log = InMemoryStructuredLogger()
    for i in range(10):
        log.info("m", i=i)
    values = [json.loads(r)["i"] for r in log.records]
    assert values == list(range(10))


def test_metamorphic_redaction_is_idempotent() -> None:
    log = InMemoryStructuredLogger()
    log.info("s", k="Bearer abcdef123456")
    first = log.records[-1]
    # Re-emitting the already-redacted value does not further mangle it.
    second_log = InMemoryStructuredLogger()
    second_log.info("s", k=json.loads(first)["k"])
    assert json.loads(second_log.records[0])["k"] == json.loads(first)["k"]


def test_differential_debug_vs_info_same_schema() -> None:
    log = InMemoryStructuredLogger()
    log.debug("d"); log.info("i"); log.warn("w"); log.error("e")
    for line in log.records:
        rec = json.loads(line)
        assert set(["ts", "level", "event"]).issubset(rec.keys())


def test_metamorphic_trace_id_echoes_in_every_emission_while_active() -> None:
    log = InMemoryStructuredLogger()
    log.activate_span("c" * 32, "d" * 16)
    for _ in range(5):
        log.info("m")
    for line in log.records:
        rec = json.loads(line)
        assert rec["trace_id"] == "c" * 32
