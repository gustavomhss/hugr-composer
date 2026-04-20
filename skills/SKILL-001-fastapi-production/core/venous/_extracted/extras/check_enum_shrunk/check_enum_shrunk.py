from __future__ import annotations
from typing import Any


def check_enum_shrunk(baseline: dict[str, Any], current: dict[str, Any], path: str='') -> list[str]:
    """Detect enum fields that lost values between baseline and current.

    Args:
        baseline: Baseline OpenAPI component schema properties dict.
        current: Current OpenAPI component schema properties dict.
        path: Dot-separated schema path for error messages.

    Returns:
        List of violation strings, empty if no enum shrinkage detected.
    """
    violations: list[str] = []
    for field, spec in baseline.items():
        if field not in current:
            continue
        old_enum = set(spec.get('enum') or [])
        new_enum = set(current[field].get('enum') or [])
        if not old_enum:
            continue
        removed = old_enum - new_enum
        if removed:
            violations.append(f"BREAKING: enum field '{path}.{field}' lost values: " + ', '.join(sorted((str(v) for v in removed))))
    return violations
