"""Red Team adversarial test suite for SKILL-001 adapt tools.

Every attack is a self-contained function.  Each returns a dict::

    {"name": str, "category": str, "passed": bool, "notes": str}

``passed=True`` means the tool handled the adversarial input *gracefully*
(returned a well-formed ``ToolResult`` or raised a clean validation error
without crashing, corrupting files, or producing incorrect behaviour).

Run::

    PYTHONPATH=. python3 audit/red_team.py

The implementation is split across :mod:`audit.red_team__impl1`
(shared bootstrap/helpers + fuzzing attacks), :mod:`audit.red_team__impl2`
(idempotency + conflict attacks), and :mod:`audit.red_team__impl3`
(code-quality attacks, the attack registry, and the runner) to keep each
module under the 500-LOC cap.  This module re-exports the public surface so
importers and the ``__main__`` entry point behave identically to the
pre-split single file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make sure SKILL root is on sys.path
# ---------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

# ---------------------------------------------------------------------------
# Re-export the public surface (preserved API)
# ---------------------------------------------------------------------------
from audit.red_team__impl1 import (  # noqa: E402,F401
    ATTACK_TIMEOUT,
    _all_py_parse_ok,
    _count_disk_files,
    _import_all_extend_tools,
    _is_valid_tool_result,
    _make_result,
    _run_with_timeout,
    _TimeoutError,
)
from audit.red_team__impl1 import (
    SKILL_ROOT as _IMPL_SKILL_ROOT,  # noqa: F401  (kept for parity)
)
from audit.red_team__impl3 import ALL_ATTACKS, run_red_team  # noqa: E402,F401

__all__ = [
    "ATTACK_TIMEOUT",
    "ALL_ATTACKS",
    "run_red_team",
]


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("SKILL-001 Red Team — Adversarial Test Suite")
    print("=" * 70)
    print()

    report = run_red_team()

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total attacks : {report['total_attacks']}")
    print(f"Passed        : {report['passed']}")
    print(f"Failed        : {report['failed']}")
    print()

    if report["failed"]:
        print("FAILED attacks (diagnostic — tools need attention):")
        for d in report["details"]:
            if not d["passed"]:
                print(f"  [{d['category']}] {d['name']}: {d['notes']}")
        print()

    pct = report["passed"] / report["total_attacks"] * 100
    verdict = "Red team: PASS" if report["failed"] == 0 else "Red team: FAIL"
    print(f"{verdict} — {report['passed']}/{report['total_attacks']} attacks passed ({pct:.0f}%)")

    sys.exit(0 if report["failed"] == 0 else 1)
