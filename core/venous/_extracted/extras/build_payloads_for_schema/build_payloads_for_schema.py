from __future__ import annotations
from typing import Any


def build_payloads_for_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a list of adversarial payload dicts for a JSON schema.

    Each payload has one field set to an adversarial value while others
    carry a minimal valid default so the request is structurally parseable.

    Args:
        schema: JSON Schema dict describing the request body properties.

    Returns:
        List of adversarial payload dicts (capped at _MAX_PAYLOADS_PER_SCHEMA).
    """
    props = schema.get('properties', {})
    if not props:
        return [_empty_payload(), _huge_payload(), _nested_null()]
    payloads: list[dict[str, Any]] = []
    defaults = _default_values(props)
    for field_name, field_schema in list(props.items())[:8]:
        field_type = field_schema.get('type', 'string')
        gen = _FIELD_TYPE_GENERATORS.get(field_type, string_values)
        for value in gen()[:3]:
            payload = dict(defaults)
            payload[field_name] = value
            payloads.append(payload)
            if len(payloads) >= _MAX_PAYLOADS_PER_SCHEMA:
                return payloads
    return payloads or [_empty_payload()]
