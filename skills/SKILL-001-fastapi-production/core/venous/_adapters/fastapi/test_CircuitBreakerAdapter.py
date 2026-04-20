"""Tests for the FastAPI `CircuitBreakerAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import CircuitBreakerAdapter

    assert hasattr(CircuitBreakerAdapter, "install")
    assert hasattr(CircuitBreakerAdapter, "get_breaker")
    assert hasattr(CircuitBreakerAdapter, "breaker")


def test_install_attaches_registry() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.CircuitBreakerAdapter import install

    app = FastAPI()
    reg = install(app)
    assert app.state.circuit_breakers is reg
    assert reg == {}


def test_get_breaker_lazy_creates_and_caches() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.CircuitBreakerAdapter import get_breaker, install
    from core.venous.resiliency.CircuitBreaker.CircuitBreaker import InMemoryCircuitBreaker

    app = FastAPI()
    install(app)
    cb1 = get_breaker(app, "svc_a")
    cb2 = get_breaker(app, "svc_a")
    cb3 = get_breaker(app, "svc_b")
    assert isinstance(cb1, InMemoryCircuitBreaker)
    assert cb1 is cb2
    assert cb1 is not cb3
    assert cb1.state == "closed"


def test_breaker_depends_factory_returns_callable() -> None:
    from core.venous._adapters.fastapi.CircuitBreakerAdapter import breaker

    dep = breaker("any")
    assert callable(dep)


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_registry,
        test_get_breaker_lazy_creates_and_caches,
        test_breaker_depends_factory_returns_callable,
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
