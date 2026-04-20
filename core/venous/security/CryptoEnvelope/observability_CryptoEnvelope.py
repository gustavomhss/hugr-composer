"""Observability harness — schema well-formedness + runtime surface assertions.

The reference in-memory CryptoEnvelope does not wire OTel counters; the schema
declares the contract that production adapters (KMS, HSM) MUST uphold. These
tests enforce schema shape + forbid plaintext-like fields in emitted signals.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from CryptoEnvelope import AeadEnvelope, InMemoryKeyVault

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"

_PLAINTEXT_FORBIDDEN = frozenset(
    {"plaintext", "pt", "secret", "secret_value", "aad", "key", "key_material",
     "key_bytes", "raw_key"}
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


def test_observability_span_ops_include_seal_and_open() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "crypto_envelope.seal" in ops
    assert "crypto_envelope.open" in ops


def test_observability_no_plaintext_or_key_in_schema_attributes() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in _PLAINTEXT_FORBIDDEN, (
                f"forbidden attribute {attr!r} in log {log['event_name']!r}"
            )
    for m in schema["metrics"]:
        for attr in m["label_keys"]:
            assert attr not in _PLAINTEXT_FORBIDDEN
    for s in schema["spans"]:
        for attr in s["required_attributes"]:
            assert attr not in _PLAINTEXT_FORBIDDEN


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_nonce_collision_signal_present() -> None:
    """CRY-INV-02: nonce collision MUST be emitted as a dedicated log + metric."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    metric_names = {m["name"] for m in schema["metrics"]}
    assert "crypto_envelope.nonce.collision_detected" in log_names
    assert "crypto_envelope.nonce.collisions" in metric_names


def test_observability_seal_open_roundtrip_is_observable_surface() -> None:
    """The primitive's public surface emits no plaintext even at the raw
    representation layer — the reference impl's Envelope does not echo pt."""
    v = InMemoryKeyVault()
    v.register("k1", secrets.token_bytes(32))
    env = AeadEnvelope(v)
    canary = b"OBS-CANARY-0xFEEDFACE"
    sealed = env.seal(canary, b"aad")
    # Nothing a tracer/log exporter could reach via the Envelope's repr
    # carries the plaintext.
    assert canary not in repr(sealed).encode("utf-8", "ignore")
    # Round-trip succeeds so the metric path would record outcome=ok.
    assert env.open(sealed, b"aad") == canary
