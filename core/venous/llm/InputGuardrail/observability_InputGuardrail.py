"""Observability harness — asserts InputGuardrail emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from InputGuardrail import Chain, DenyList, GuardBlocked, PIIRedactor, PromptInjectionBlocker


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_required_operation_names_declared() -> None:
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "inputguardrail.chain.apply" in span_ops
    assert "inputguardrail.guard.evaluate" in span_ops


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_block_event_includes_hash_not_clear_text() -> None:
    """GUARD-INV-05: the blocked event's required attribute list names the HASH,
    not the raw text, so no exporter can accidentally stream clear text."""
    schema = _load_schema()
    blocked = next(
        log for log in schema["logs"]
        if log["event_name"] == "inputguardrail.decision.blocked"
    )
    required = list(blocked["required_attributes"])
    assert "input_hash" in required
    assert "raw_text" not in required
    assert "text" not in required


def test_observability_audit_log_records_actions_in_order() -> None:
    """Runtime: the audit log preserves the order of decisions, which feeds the
    metrics pipeline with `action` label."""
    chain = Chain([PIIRedactor(), PromptInjectionBlocker()])
    chain.apply("email bob@example.com please", {})
    actions = [e.action for e in chain.audit]
    assert actions == ["redact", "allow"]


def test_observability_block_event_carries_hashed_input() -> None:
    chain = Chain([DenyList("d", terms=["zzz"])])
    with pytest.raises(GuardBlocked):
        chain.apply("bad zzz input", {})
    # Runtime mirror of the schema: the block row's input_hash is populated.
    entry = chain.audit[-1]
    assert entry.action == "block"
    assert entry.input_hash and "bad zzz input" not in entry.input_hash
