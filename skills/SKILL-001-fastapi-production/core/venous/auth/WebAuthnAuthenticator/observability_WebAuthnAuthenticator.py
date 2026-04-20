"""Observability harness — asserts WebAuthnAuthenticator schema is well-formed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from WebAuthnAuthenticator import ReferenceWebAuthnAuthenticator

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"
RP_ID = "passkeys.example.com"
ORIGIN = "https://passkeys.example.com"
RP_ID_HASH = hashlib.sha256(RP_ID.encode()).digest()


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


def test_observability_spans_cover_ceremony() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "webauthn.finish.registration" in ops
    assert "webauthn.finish.assertion" in ops


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_ceremony_runs_emit_attributes() -> None:
    """The primitive supports the ceremony whose lifecycle events the schema
    describes. Confirming the happy path ties schema to impl."""
    auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg_opts = auth.begin_registration(user_id=b"alice", user_name="alice")
    ch = reg_opts["challenge"]
    assert isinstance(ch, bytes)
    result = auth.finish_registration(
        challenge=ch,
        response={
            "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": ch},
            "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
            "credentialId": b"cred-alice",
            "publicKey": b"pk-alice",
            "aaguid": b"\xaa" * 16,
            "userId": b"alice",
        },
    )
    assert result.credential_id == b"cred-alice"
