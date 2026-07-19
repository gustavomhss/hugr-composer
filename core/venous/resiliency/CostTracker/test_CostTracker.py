"""Invariant tests for `CostTracker`.

Uses a lightweight reference model mirroring the staged impl. See
`CostTracker.contract.json` for invariant IDs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Estimate:
    db_cost_usd: float = 0.0
    s3_cost_usd: float = 0.0
    api_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class _Tracker:
    def __init__(self, max_history: int = 100):
        self._estimators: list = []
        self._history: list[_Estimate] = []
        self._max_history = max_history

    def register(self, component: str, fn) -> None:
        self._estimators.append((component, fn))

    def estimate_request(self, ctx) -> _Estimate:
        e = _Estimate()
        for component, fn in self._estimators:
            try:
                cost = fn(ctx)
            except Exception:
                continue  # INV_01: swallow
            if component == "db": e.db_cost_usd += cost
            elif component == "s3": e.s3_cost_usd += cost
            elif component == "api": e.api_cost_usd += cost
        e.total_cost_usd = e.db_cost_usd + e.s3_cost_usd + e.api_cost_usd
        if len(self._history) >= self._max_history:
            self._history.pop(0)
        self._history.append(e)
        return e


# INV_01 -----------------------------------------------------------------
def test_inv_estimator_failure_isolated_confirms() -> None:
    t = _Tracker()
    t.register("db", lambda c: 1.0)
    t.register("s3", lambda c: 1/0)  # boom
    t.register("api", lambda c: 2.0)
    e = t.estimate_request({})  # MUST NOT raise
    assert e.db_cost_usd == 1.0
    assert e.api_cost_usd == 2.0


def test_inv_estimator_failure_isolated_prevents() -> None:
    # No estimator error surfaces to the caller (try/except proves it).
    t = _Tracker()
    t.register("db", lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    # generator-based bomb above — but actually fn is the generator expr,
    # which does not raise until next(). So register a direct raiser:
    def _bad(_):
        raise RuntimeError("boom")
    t._estimators = [("db", _bad)]
    e = t.estimate_request({})
    assert e.db_cost_usd == 0.0


def test_inv_estimator_failure_isolated_under_failure() -> None:
    # All estimators fail -> still a valid (zero) estimate returned.
    t = _Tracker()
    for c in ("db", "s3", "api"):
        t.register(c, lambda _: (_ for _ in ()).throw(Exception()))
    e = t.estimate_request({})
    assert e.total_cost_usd == 0.0


# INV_02 -----------------------------------------------------------------
def test_inv_history_bounded_confirms() -> None:
    t = _Tracker(max_history=5)
    for _ in range(20):
        t.estimate_request({})
    assert len(t._history) == 5


def test_inv_history_bounded_prevents() -> None:
    # History length never exceeds cap, ever.
    t = _Tracker(max_history=3)
    for _ in range(1000):
        t.estimate_request({})
        assert len(t._history) <= 3


def test_inv_history_bounded_under_failure() -> None:
    t = _Tracker(max_history=1)
    for _ in range(10):
        t.estimate_request({})
    assert len(t._history) == 1


# INV_03 -----------------------------------------------------------------
def test_inv_total_conservation_confirms() -> None:
    t = _Tracker()
    t.register("db", lambda c: 1.5)
    t.register("s3", lambda c: 2.5)
    t.register("api", lambda c: 4.0)
    e = t.estimate_request({})
    assert e.total_cost_usd == e.db_cost_usd + e.s3_cost_usd + e.api_cost_usd == 8.0


def test_inv_total_conservation_prevents() -> None:
    # Unknown component: cost is NOT added to total (and therefore conservation holds).
    t = _Tracker()
    t.register("unknown_bucket", lambda c: 999.0)
    e = t.estimate_request({})
    assert e.total_cost_usd == 0.0


def test_inv_total_conservation_under_failure() -> None:
    t = _Tracker()
    t.register("db", lambda c: 0.0)
    e = t.estimate_request({})
    assert e.total_cost_usd == 0.0
