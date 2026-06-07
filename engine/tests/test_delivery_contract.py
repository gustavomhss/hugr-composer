"""
Meta-tests for the primitive delivery contract.

Goal: prove each validator in `primitive_delivery_contract.py` accepts valid
input and rejects every specific failure mode. Every rejection path gets at
least one test. If a rule is not tested here, it is not enforced in practice.

This module was split for the ≤500-LOC file cap. The actual tests now live in
sibling modules; this file only re-exports them so the historical entrypoints
keep working:

    python3 -m engine.tests.test_delivery_contract   # manual pytest-less runner
    pytest engine/tests/test_delivery_contract__*.py # via pytest

The shared fixture factory lives in `test_delivery_contract__shared.py`. The
test bodies live in:

    test_delivery_contract__part1.py  — positive deliveries, identity, files
    test_delivery_contract__part2.py  — bindings, tiers, sub-reports, cost cap
    test_delivery_contract__part3.py  — ensemble/judge/persona/obs + field bounds
"""

from __future__ import annotations

import sys
import traceback


def _run() -> int:
    # Aggregate every test_* across the split modules so the manual runner keeps
    # the same behaviour it had before the file was split.
    from engine.tests import (  # noqa: F401
        test_delivery_contract__part1 as _p1,
    )
    from engine.tests import (
        test_delivery_contract__part2 as _p2,
    )
    from engine.tests import (
        test_delivery_contract__part3 as _p3,
    )

    tests: list = []
    for mod in (_p1, _p2, _p3):
        tests.extend(v for k, v in vars(mod).items() if k.startswith("test_") and callable(v))

    passed = 0
    failed: list[tuple[str, str]] = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✓ {t.__name__}")
        except Exception:
            failed.append((t.__name__, traceback.format_exc()))
            print(f"  ✗ {t.__name__}")
    print(f"\n{passed}/{len(tests)} passed")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_run())
