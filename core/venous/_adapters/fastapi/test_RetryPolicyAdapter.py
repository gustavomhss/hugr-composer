"""Tests for the FastAPI `RetryPolicyAdapter`."""

from __future__ import annotations

import asyncio


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import RetryPolicyAdapter

    assert hasattr(RetryPolicyAdapter, "install")
    assert hasattr(RetryPolicyAdapter, "policy_dep")
    assert hasattr(RetryPolicyAdapter, "budget")


def test_install_attaches_policy() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.RetryPolicyAdapter import install
    from core.venous.resiliency.RetryPolicy.RetryPolicy import ExponentialBackoffRetryPolicy

    app = FastAPI()
    p = install(app, max_attempts=4, initial_interval_ms=50)
    assert isinstance(p, ExponentialBackoffRetryPolicy)
    assert app.state.retry_policy is p
    assert p.max_attempts == 4


def test_policy_executes_retry() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.RetryPolicyAdapter import install

    app = FastAPI()
    p = install(app, max_attempts=3, initial_interval_ms=1, jitter=0.0, budget_ratio=1.0)
    calls = {"n": 0}

    async def fn() -> int:
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("flaky")
        return 42

    # Seed budget with a prior success so retry admission passes
    p.budget.record_success()
    result = asyncio.run(p.execute(fn, idempotent=True))
    assert result == 42
    assert calls["n"] == 2


def test_budget_helper_constructs_timeoutbudget() -> None:
    from core.venous._adapters.fastapi.RetryPolicyAdapter import budget

    b = budget(500)
    assert b.remaining_ms == 500


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_policy,
        test_policy_executes_retry,
        test_budget_helper_constructs_timeoutbudget,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)
