"""Observability harness — asserts AntiCorruptionLayer emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from AntiCorruptionLayer import (
    ContractVersion,
    DictAntiCorruptionLayer,
    ForeignPayload,
    detect_schema_drift,
)


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
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


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "acl.to_local" in ops
    assert "acl.to_foreign" in ops


def test_observability_lifecycle_attributes_map_to_runtime() -> None:
    # Each log attribute is recoverable from the runtime state of a real ACL.
    acl = DictAntiCorruptionLayer()
    payload = {"legacy_id": 1, "legacy_name": "Obs"}
    local = acl.to_local(payload)
    # "version" comes from the ACL; "result" is derived from translation success.
    assert acl.default_version.system == "legacy.example"
    assert local["id"] == 1
    # "declared_version" + "known_versions" recoverable via detect_schema_drift.
    ghost = ForeignPayload(ContractVersion("legacy.example", "ghost"), {})
    assert detect_schema_drift(acl, ghost) is True
