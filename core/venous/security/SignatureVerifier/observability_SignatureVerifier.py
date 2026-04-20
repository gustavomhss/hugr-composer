"""Observability harness — schema well-formedness + runtime surface assertions.

The reference in-memory SignatureVerifier does not wire OTel counters; the
schema declares the contract that production adapters (KMS, HSM) MUST uphold.
These tests enforce schema shape + forbid key / signature fields in emitted
signals.
"""

from __future__ import annotations

import json
from pathlib import Path

from SignatureVerifier import (
    ALG_ED25519,
    DetachedSigner,
    TrustAnchor,
    generate_ed25519_keypair,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"

_FORBIDDEN_ATTRS = frozenset(
    {"private_key", "secret", "secret_value", "signature", "signature_bytes",
     "raw_key", "key_material", "key_bytes", "message", "plaintext"}
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


def test_observability_span_ops_include_sign_and_verify() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "signature_verifier.sign" in ops
    assert "signature_verifier.verify" in ops


def test_observability_no_secret_fields_in_schema_attributes() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in _FORBIDDEN_ATTRS, (
                f"forbidden attribute {attr!r} in log {log['event_name']!r}"
            )
    for m in schema["metrics"]:
        for attr in m["label_keys"]:
            assert attr not in _FORBIDDEN_ATTRS
    for s in schema["spans"]:
        for attr in s["required_attributes"]:
            assert attr not in _FORBIDDEN_ATTRS


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_replay_signal_present() -> None:
    """SIG-INV-01: replay detections MUST be emitted as dedicated log + metric."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    metric_names = {m["name"] for m in schema["metrics"]}
    assert "signature_verifier.replay.detected" in log_names
    assert "signature_verifier.replay.detections" in metric_names


def test_observability_sign_verify_surface_leaks_no_secret() -> None:
    """Primitive's public surface emits no secret material even at raw repr."""
    anchor = TrustAnchor()
    sk, pk = generate_ed25519_keypair()
    canary = sk  # the private key is the most sensitive bytes we have
    anchor.register("k1", ALG_ED25519, public_key=pk, private_key=sk)
    signer = DetachedSigner(anchor, default_msg_type="obs")
    sig = signer.sign(b"payload", "k1")
    signer.verify(b"payload", sig, "k1")
    # repr of the signer / anchor / resolve record MUST NOT echo the raw sk.
    assert canary not in repr(signer).encode("utf-8", "ignore")
    assert canary not in repr(anchor).encode("utf-8", "ignore")
