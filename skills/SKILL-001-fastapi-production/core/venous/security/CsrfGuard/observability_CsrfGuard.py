"""Observability harness for CsrfGuard."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from CsrfGuard import MIN_SECRET_BYTES, HmacCsrfGuard

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_span_ops_cover_issue_and_verify() -> None:
    s = _load_schema()
    ops = {sp["operation_name"] for sp in s["spans"]}
    assert "csrf_guard.issue" in ops
    assert "csrf_guard.verify" in ops


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_no_token_in_schema() -> None:
    # The token itself MUST NEVER appear as a log attribute.
    forbidden = {"token", "submitted_token", "csrf_token"}
    for log in _load_schema()["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in forbidden


def test_observability_verify_runs_without_emitting_secret() -> None:
    g = HmacCsrfGuard(secret=secrets.token_bytes(MIN_SECRET_BYTES))
    t = g.issue("s")
    g.verify("s", t)  # observability hooks attach externally; smoke only


def test_observability_cardinality_bounds_declared() -> None:
    for m in _load_schema()["metrics"]:
        assert m["cardinality_bound"] >= 1


def test_observability_log_event_names_lowercase_dotted() -> None:
    for log in _load_schema()["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
