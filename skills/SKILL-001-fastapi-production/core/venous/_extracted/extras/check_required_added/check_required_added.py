from __future__ import annotations
from typing import Any


def check_required_added(baseline: dict[str, Any], current: dict[str, Any], path: str='') -> list[str]:
    """Detect required fields added that were not required in baseline.

    Args:
        baseline: Baseline OpenAPI schema dict (with 'required' key).
        current: Current OpenAPI schema dict (with 'required' key).
        path: Dot-separated schema path for error messages.

    Returns:
        List of violation strings, empty if no new required fields.
    """
    violations: list[str] = []
    old_required = set(baseline.get('required') or [])
    new_required = set(current.get('required') or [])
    for field in sorted(new_required - old_required):
        violations.append(f"BREAKING: field '{path}.{field}' is now required (was optional in baseline)")
    return violations
