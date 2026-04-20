from __future__ import annotations
from typing import Any


def check_response_shape_changed(baseline_responses: dict[str, Any], current_responses: dict[str, Any], path: str='') -> list[str]:
    """Detect top-level response keys removed from successful responses.

    Args:
        baseline_responses: Baseline OpenAPI responses dict for an endpoint.
        current_responses: Current OpenAPI responses dict for an endpoint.
        path: Endpoint path for error messages.

    Returns:
        List of violation strings, empty if response shape unchanged.
    """
    violations: list[str] = []
    for status_code in ('200', '201'):
        old_resp = baseline_responses.get(status_code, {})
        new_resp = current_responses.get(status_code, {})
        if not old_resp:
            continue
        old_keys = set(_extract_response_keys(old_resp))
        new_keys = set(_extract_response_keys(new_resp))
        for key in sorted(old_keys - new_keys):
            violations.append(f"BREAKING: response key '{key}' removed from {path} {status_code}")
    return violations
