"""Self-test: run all generator edge cases and verify correctness.

Usage:
    python benchmark/test_generators.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure generators are importable
SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from generators.orchestrator import generate_project
from benchmark.analyzer import analyze
from benchmark.import_audit import audit


TESTS = [
    ("minimal (no auth, no models)", dict(name="minimal", with_auth=False)),
    ("auth only (no domain models)", dict(name="authonly")),
    ("single model + owner", dict(
        name="blog",
        models={"Post": {"title": "str", "body": "text"}},
        owner_models={"Post": "user"},
    )),
    ("multi-model mixed owners", dict(
        name="shop",
        models={
            "Product": {"name": "str", "price": "Decimal"},
            "Order": {"status": "str", "total": "Decimal"},
            "Category": {"name": "str", "slug": "str"},
        },
        owner_models={"Order": "user"},
    )),
    ("full options", dict(
        name="full",
        models={"Task": {"title": "str", "done": "bool"}},
        owner_models={"Task": "user"},
        with_redis=True, with_k8s=True, with_ci=True,
        with_loadtest=True, with_otel=True, with_prometheus=True, with_alerting=True,
    )),
    ("models without auth", dict(
        name="public",
        models={"Article": {"title": "str", "content": "text"}},
        with_auth=False,
    )),
    ("with redis", dict(
        name="cached",
        models={"Entry": {"key": "str", "value": "text"}},
        with_redis=True,
    )),
    ("benchmark spec (User + Item)", dict(
        name="bench",
        prefix="/api/v1",
        models={"Item": {"title": "str", "description": "text"}},
        owner_models={"Item": "user"},
        cors_origins=["http://localhost:3000"],
    )),
]


def run_tests() -> bool:
    passed = 0
    failed = 0

    for test_name, kwargs in TESTS:
        d = tempfile.mkdtemp()
        try:
            result = generate_project(output_dir=d, **kwargs)
            bench = analyze(d)
            import_errors = audit(Path(d))

            if import_errors:
                failed += 1
                print(f"FAIL  {test_name}: {len(import_errors)} import error(s)")
                for e in import_errors[:3]:
                    print(f"      {e}")
            else:
                passed += 1
                print(f"PASS  {test_name}: {result['total_files']} files, {bench.passed}/{bench.total} bench")
        except Exception as e:
            failed += 1
            print(f"CRASH {test_name}: {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(d)

    print(f"\n{'=' * 50}")
    print(f"  RESULTS: {passed}/{passed + failed} passed")
    print(f"{'=' * 50}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
