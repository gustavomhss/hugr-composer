"""Observability harness."""

from __future__ import annotations

import json
from pathlib import Path

from FeatureToggle import FeatureToggleRegistry, ToggleContext


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_names_dotted() -> None:
    for log in _load_schema()["logs"]:
        name = str(log["event_name"])
        assert "." in name and name == name.lower()


def test_observability_span_names_dotted() -> None:
    for span in _load_schema()["spans"]:
        op = str(span["operation_name"])
        assert "." in op and op == op.lower()


def test_observability_cardinality_declared() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_audit_trail_shape() -> None:
    class T:
        def __init__(self, key: str) -> None:
            self.key = key

        def is_active(self, ctx: ToggleContext) -> bool:
            return False

    reg = FeatureToggleRegistry()
    reg.register(T("visible_flag"))
    ctx = ToggleContext(principal_id="p", tenant_id="t", environment="prod")
    reg.is_active("visible_flag", ctx)
    entry = reg.audit[-1]
    # Shape matches the declared log schema (key + decision + tenant + env).
    for attr in ("key", "decision", "ctx_tenant", "ctx_environment"):
        assert hasattr(entry, attr)
