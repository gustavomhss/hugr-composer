"""Observability harness — asserts TotpVerifier schema is well-formed and the
primitive emits the right behavioral signals for logs/metrics/spans."""

from __future__ import annotations

import json
from pathlib import Path

from TotpVerifier import (
    DEFAULT_STEP_SECONDS,
    StandardTotpVerifier,
    TotpReplayError,
    _hotp,  # type: ignore[attr-defined]
    generate_secret,
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
    assert "totp.verify" in ops
    assert "totp.provision_uri" in ops


def test_observability_verify_emits_accept_and_replay_outcomes() -> None:
    # Behavioral proof that the primitive distinguishes accept vs replay
    # outcomes — these are the discrete signal classes the schema declares.
    secret = generate_secret()
    now = 1_700_000_000.0
    step = int(now // DEFAULT_STEP_SECONDS)
    code = _hotp(secret, step, 6, "SHA1")
    v = StandardTotpVerifier(now_fn=lambda: now)
    assert v.verify(secret=secret, code=code, last_used_step=None) == step

    # Second call is the replay-detected signal class.
    v2 = StandardTotpVerifier(now_fn=lambda: now)
    replay_rejected = False
    try:
        v2.verify(secret=secret, code=code, last_used_step=step)
    except TotpReplayError:
        replay_rejected = True
    assert replay_rejected
