"""Chaos / fault-injection scenarios."""

from __future__ import annotations

import threading

import pytest

from FeatureToggle import (
    FeatureToggleInvariantError,
    FeatureToggleRegistry,
    ToggleContext,
)


class ExplodingToggle:
    def __init__(self, key: str, exc_type: type[BaseException]) -> None:
        self.key = key
        self._exc = exc_type

    def is_active(self, ctx: ToggleContext) -> bool:
        raise self._exc("boom")


def test_chaos_evaluation_failure_defaults_off() -> None:
    reg = FeatureToggleRegistry()
    for exc in (RuntimeError, ValueError, ConnectionError, MemoryError):
        key = f"crasher_{exc.__name__.lower()}"
        reg.register(ExplodingToggle(key, exc))
        ctx = ToggleContext(principal_id=None, tenant_id=None, environment="prod")
        for _ in range(3):
            assert reg.is_active(key, ctx) is False


def test_chaos_ctx_type_enforced() -> None:
    reg = FeatureToggleRegistry()
    for bad in ({"environment": "prod"}, "prod", 42, None, object()):
        with pytest.raises(FeatureToggleInvariantError):
            reg.is_active("x", bad)  # type: ignore[arg-type]


def test_chaos_concurrent_registration_race() -> None:
    class T:
        def __init__(self, key: str) -> None:
            self.key = key

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    results: list[str] = []

    def worker(i: int) -> None:
        try:
            reg.register(T(f"concurrent_key_{i}"))
        except FeatureToggleInvariantError as e:
            results.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All unique keys registered; no errors.
    assert results == []
    assert len(reg.known_keys()) == 50


def test_chaos_double_delete_rejected() -> None:
    class T:
        def __init__(self, key: str) -> None:
            self.key = key

        def is_active(self, ctx: ToggleContext) -> bool:
            return False

    reg = FeatureToggleRegistry()
    reg.register(T("once_more"))
    reg.mark_stale("once_more")
    reg.delete("once_more")
    with pytest.raises(FeatureToggleInvariantError):
        reg.delete("once_more")


def test_chaos_audit_under_high_load() -> None:
    class T:
        def __init__(self, key: str) -> None:
            self.key = key

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    reg.register(T("load_flag"))
    ctx = ToggleContext(principal_id="p", tenant_id="t", environment="prod")
    N = 2000
    for _ in range(N):
        reg.is_active("load_flag", ctx)
    assert len(reg.audit) == N


def test_chaos_malicious_key_rejected() -> None:
    class T:
        def __init__(self, key: str) -> None:
            self.key = key

        def is_active(self, ctx: ToggleContext) -> bool:
            return True

    reg = FeatureToggleRegistry()
    for bad in ("../etc/passwd", "key with space", "KeyWithCaps", "k", "", "a" * 200):
        with pytest.raises(FeatureToggleInvariantError):
            reg.register(T(bad))


def test_chaos_empty_registry_returns_false_everywhere() -> None:
    reg = FeatureToggleRegistry()
    ctx = ToggleContext(principal_id=None, tenant_id=None, environment="dev")
    for key in ("feature_a", "feature_b", "something_else", "plain_x", "plain_y"):
        assert reg.is_active(key, ctx) is False
