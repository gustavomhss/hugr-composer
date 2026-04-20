"""Observability harness — schema well-formedness + runtime assertions.

The reference ContentSecurityPolicy does not itself emit OTel signals; the
schema declares the contract a production middleware MUST uphold. These
tests enforce schema shape and forbid any attribute that could leak a
nonce value or raw header body into a low-trust sink.
"""

from __future__ import annotations

import json
from pathlib import Path

from ContentSecurityPolicy import (
    CspPolicy,
    _DEFAULT_REGISTRY,
    generate_nonce,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"

_FORBIDDEN_ATTRS = frozenset(
    {"nonce", "nonce_value", "header", "header_value", "raw", "secret"},
)


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    for key in ("logs", "metrics", "spans"):
        assert isinstance(schema[key], list) and schema[key]


def test_observability_metric_types_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_span_ops_cover_render_and_nonce() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "csp.render_header" in ops
    assert "csp.with_nonce" in ops


def test_observability_no_nonce_value_in_schema_attributes() -> None:
    """CSP_INV_03: the nonce VALUE must never appear in telemetry.

    Bytes-count is fine; the value itself is not.
    """
    schema = _load_schema()
    for log in schema["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in _FORBIDDEN_ATTRS, (
                f"forbidden attr {attr!r} in log {log['event_name']!r}"
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


def test_observability_rejection_signal_present() -> None:
    """CSP_INV_01..06: rejections surface under a dedicated log + metric."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    metric_names = {m["name"] for m in schema["metrics"]}
    assert "csp.policy.rejected" in log_names
    assert "csp.policy.rejections" in metric_names


def test_observability_nonce_reuse_signal_present() -> None:
    """CSP_INV_03: nonce reuse surfaces as a dedicated signal so SRE alerts."""
    schema = _load_schema()
    log_names = {log["event_name"] for log in schema["logs"]}
    metric_names = {m["name"] for m in schema["metrics"]}
    assert "csp.nonce.reused" in log_names
    assert "csp.nonces.reused" in metric_names


def test_observability_rendering_does_not_expose_nonce_value_in_to_dict() -> None:
    """CSP_INV_03: `CspPolicy.to_dict` redacts the nonce by encoding it as a
    source token in the directive list; the nonce value appears there (it
    must, by the spec — the browser needs it), but no *separate* nonce
    attribute is exposed that a naive exporter could pick up and label as
    'secret' or 'token'."""
    _DEFAULT_REGISTRY.reset()
    nonce = generate_nonce()
    p = CspPolicy.strict_default().with_nonce(nonce)
    d = p.to_dict()
    # No top-level key called `nonce` / `nonce_value`.
    for forbidden in _FORBIDDEN_ATTRS:
        assert forbidden not in d
    # Nonce appears in-band on the script-src source list, never as a
    # separate attribute that would get serialized as a span/log secret.
    assert any(
        f"'nonce-{nonce}'" in s for s in d["directives"]["script-src"]  # type: ignore[index]
    )
