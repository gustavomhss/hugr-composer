"""Closed set of failure codes carried by the tier-1 / compose envelopes.

Every envelope with ``ok=False`` carries exactly one of these in ``code``.
The free-text ``what_happened`` may contain paths or backend detail, so
native callers (the OpenCode HuGR Composer bridge) redact it and forward
only ``code``. That bridge mirrors this set; adding or renaming a code is a
contract change on both sides.
"""

from __future__ import annotations

ERROR_CODES = frozenset(
    {
        # input selection
        "missing-selection",
        "unknown-recipe",
        "unknown-primitive",
        "recipe-mismatch",
        "domain-boundary",
        "empty-query",
        "not-found",
        "unknown-skill",
        "unknown-bundle",
        # output placement
        "path-rejected",
        "target-exists",
        # backend execution
        "invalid-output",
        "write-failed",
        "scaffold-failed",
        "backend-unavailable",
        "catalog-invalid",
        "audit-failed",
        "verify-failed",
    }
)


def require_code(ok: bool, code: str | None) -> str | None:
    """Enforce the envelope invariant: failures name a known code, successes none."""
    if ok and code is not None:
        raise ValueError(f"successful envelope must not carry code {code!r}")
    if not ok and code not in ERROR_CODES:
        raise ValueError(f"failed envelope needs a code from ERROR_CODES, got {code!r}")
    return code
