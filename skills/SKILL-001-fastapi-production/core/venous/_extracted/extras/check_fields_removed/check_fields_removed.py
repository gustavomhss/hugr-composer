from __future__ import annotations
from typing import Any


def check_fields_removed(baseline: dict[str, Any], current: dict[str, Any], path: str='') -> list[str]:
    """Detect fields present in baseline but absent in current schema.

    Args:
        baseline: Baseline OpenAPI component schema properties dict.
        current: Current OpenAPI component schema properties dict.
        path: Dot-separated schema path for error messages.

    Returns:
        List of violation strings, empty if no removals detected.
    """
    violations: list[str] = []
    for field, _spec in baseline.items():
        if field not in current:
            violations.append(f"BREAKING: field '{path}.{field}' removed from schema")
    return violations
