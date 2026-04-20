"""Observability harness — asserts CurrentPrincipal emits logs/metrics matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from CurrentPrincipal import REDACTED, anonymous, authenticated

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


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


def test_observability_for_log_fields_match_schema_required_attributes() -> None:
    p = authenticated("alice", tenant_id="t1", roles=["admin"], claims={"k": "v"})
    log = p.for_log()
    schema = _load_schema()
    resolved_entry = next(
        entry for entry in schema["logs"] if entry["event_name"] == "auth.principal.resolved"
    )
    required = resolved_entry["required_attributes"]
    assert isinstance(required, list)
    for attr in required:
        assert attr in log, f"for_log() missing required attribute {attr!r}"


def test_observability_anonymous_log_fields_present() -> None:
    log = anonymous().for_log()
    for key in ("subject_id", "tenant_id", "roles", "is_anonymous", "claims"):
        assert key in log


def test_observability_no_raw_claim_values_in_log_payload() -> None:
    p = authenticated("a", claims={"token": "sk-leak", "email": "a@b.c"})
    payload = json.dumps(p.for_log())
    assert "sk-leak" not in payload
    assert "a@b.c" not in payload
    assert REDACTED in payload
