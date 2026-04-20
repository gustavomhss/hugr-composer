"""Observability harness — schema well-formedness + runtime surface assertions.

The reference in-memory SecretsVault does not wire OTel counters; the schema
declares the contract that production adapters (KMS, HashiCorp Vault) MUST
uphold. These tests enforce schema shape + forbid material-like fields in
emitted signals.
"""

from __future__ import annotations

import json
from pathlib import Path

from SecretsVault import (
    CachingSecretsVault,
    InMemoryAuditSink,
    InMemoryBackend,
    caller_identity,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"

_MATERIAL_FORBIDDEN = frozenset(
    {
        "material", "secret_value", "secret", "plaintext", "value",
        "raw", "key", "key_material", "payload", "body",
    }
)


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    for key in ("logs", "metrics", "spans"):
        assert isinstance(schema[key], list) and schema[key]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_span_ops_cover_get_rotate_invalidate() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "secrets_vault.get" in ops
    assert "secrets_vault.rotate" in ops
    assert "secrets_vault.invalidate" in ops


def test_observability_no_material_fields_in_schema_attributes() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in _MATERIAL_FORBIDDEN, (
                f"forbidden attribute {attr!r} in log {log['event_name']!r}"
            )
    for m in schema["metrics"]:
        for attr in m["label_keys"]:
            assert attr not in _MATERIAL_FORBIDDEN
    for s in schema["spans"]:
        for attr in s["required_attributes"]:
            assert attr not in _MATERIAL_FORBIDDEN


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_backend_outage_signal_present() -> None:
    """SV-INV-05: backend outage MUST surface as a dedicated log + metric."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    metric_names = {m["name"] for m in schema["metrics"]}
    assert "secrets_vault.backend.unavailable" in log_names
    assert "secrets_vault.backend.unavailable" in metric_names


def test_observability_scope_denial_signal_present() -> None:
    """SV-INV-04: a scope denial MUST surface as a dedicated log."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    assert "secrets_vault.scope.denied" in log_names


def test_observability_audit_surface_carries_no_material() -> None:
    """The AuditEvent emitted by the reference vault has NO material field —
    so even a naive exporter cannot leak secret bytes."""
    be = InMemoryBackend()
    canary = b"OBS-CANARY-0xFEEDFACE"
    be.register("obs-secret", canary)
    sink = InMemoryAuditSink()
    vault = CachingSecretsVault(be, audit=sink)
    with caller_identity("svc"):
        sv = vault.get("obs-secret")
    assert sv.material == canary
    for e in sink.events():
        # AuditEvent.__dataclass_fields__ MUST NOT include any material field.
        fields = set(e.__dataclass_fields__.keys())
        for forbidden in _MATERIAL_FORBIDDEN:
            assert forbidden not in fields
        # And the repr MUST NOT echo the canary.
        assert canary not in repr(e).encode("utf-8", "ignore")
