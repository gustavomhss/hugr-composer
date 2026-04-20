from __future__ import annotations
from typing import Any


def check_types_changed(baseline: dict[str, Any], current: dict[str, Any], path: str='') -> list[str]:
    """Detect fields whose type changed between baseline and current.

    Args:
        baseline: Baseline OpenAPI component schema properties dict.
        current: Current OpenAPI component schema properties dict.
        path: Dot-separated schema path for error messages.

    Returns:
        List of violation strings, empty if no type changes detected.
    """
    violations: list[str] = []
    for field, spec in baseline.items():
        if field not in current:
            continue
        old_type = spec.get('type') or spec.get('$ref', '')
        new_type = current[field].get('type') or current[field].get('$ref', '')
        if old_type and new_type and (old_type != new_type):
            violations.append(f"BREAKING: field '{path}.{field}' type changed '{old_type}' -> '{new_type}'")
    return violations
