"""Observability harness for EncryptionPolicy."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from EncryptionPolicy import EncryptionPolicy, InMemoryEncryptionRegistry


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_non_empty() -> None:
    s = _schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_logs_lowercase() -> None:
    for log in _schema()["logs"]:
        assert log["event_name"] == str(log["event_name"]).lower()


def test_observability_bind_span_declared() -> None:
    ops = {str(s["operation_name"]) for s in _schema()["spans"]}
    assert "encryption.bind" in ops


def test_observability_resolve_counter_declared() -> None:
    names = {str(m["name"]) for m in _schema()["metrics"]}
    assert "encryption.resolve" in names


def test_observability_bind_runs_cleanly() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(EncryptionPolicy(
        data_class="x", at_rest_cipher="AES-256-GCM",
        in_transit_min_tls="TLS1.2", key_provider="aws-kms://k",
        rotation=timedelta(days=90),
    ))
    assert r.size == 1
