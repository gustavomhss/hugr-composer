"""Observability harness for PromptTemplate.

Validates observability_schema.json wellformedness and that the primitive's
surfaced attributes (name, version, fingerprint) are suitable as OTel span
attributes / log fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from PromptTemplate import FrozenPromptTemplate

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
    assert "prompt.render" in span_ops


def test_observability_fingerprint_is_attribute_safe() -> None:
    tpl = FrozenPromptTemplate(name="o", version=1, target_model="m",
                                text="{{x}}", variables=("x",))
    fp = tpl.fingerprint()
    # Fingerprint is ASCII, bounded length — valid as an OTel attribute value.
    assert fp.isascii()
    assert len(fp) < 200
    assert fp.startswith("sha256:")


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
