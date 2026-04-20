"""Observability harness for OutputGuardrail.

Validates observability_schema.json wellformedness and that the primitive's
surfaced attributes (guardrail name, verdict action, reason) are suitable as
OTel span attributes / log fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from OutputGuardrail import (
    PolicyOutputGuardrail,
    SafetyOutputGuardrail,
    Verdict,
    VerdictLedger,
    apply_chain,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_metric_types_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid
        assert int(m["cardinality_bound"]) >= 1


def test_observability_span_attributes_present() -> None:
    schema = _load_schema()
    span_ops = {s["operation_name"] for s in schema["spans"]}
    assert "guardrail.evaluate" in span_ops
    assert "guardrail.chain.apply" in span_ops


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_verdict_attributes_are_otel_safe() -> None:
    # Every Verdict field is a short ASCII-compatible string — safe as OTel attr.
    v = Verdict(action="rewrite", reason="redacted pii", replacement="safe")
    assert v.action.isascii()
    assert v.reason.isascii()
    assert len(v.reason) < 200


def test_observability_ledger_round_trip_for_metrics() -> None:
    # The ledger exposes exactly the cardinality needed for the
    # `guardrail.verdicts.total` counter: (guardrail_name, action).
    ledger = VerdictLedger()
    chain = [
        SafetyOutputGuardrail(name="safety"),
        PolicyOutputGuardrail(name="policy"),
    ]
    apply_chain(chain, "benign", ledger=ledger)
    apply_chain(chain, "benign", ledger=ledger)
    # Derivable counter series:
    series: dict[tuple[str, str], int] = {}
    for name, v in ledger.entries():
        key = (name, v.action)
        series[key] = series.get(key, 0) + 1
    assert series[("safety", "pass")] == 2
    assert series[("policy", "pass")] == 2


def test_observability_block_reason_bounded() -> None:
    # Reasons are bounded (MAX_REASON_CHARS) — safe for log field sizes.
    from OutputGuardrail import MAX_REASON_CHARS
    assert MAX_REASON_CHARS <= 500
