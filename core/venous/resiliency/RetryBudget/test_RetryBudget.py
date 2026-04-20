"""Invariant tests for `RetryBudget`.

Uses an in-line behavioural model mirroring the staged impl's sliding-window
semantics. See `RetryBudget.contract.json` for the invariant IDs.
"""
from __future__ import annotations

from collections import deque


class _BudgetModel:
    def __init__(self, ratio: float = 0.1, window_s: float = 60.0, min_requests: int = 10):
        self.ratio = ratio
        self.window_s = window_s
        self.min_requests = min_requests
        self._requests: deque[float] = deque()
        self._retries: deque[float] = deque()

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
        while self._retries and self._retries[0] < cutoff:
            self._retries.popleft()

    def record_request(self, t: float) -> None:
        self._requests.append(t); self._evict(t)

    def record_retry(self, t: float) -> None:
        self._retries.append(t); self._evict(t)

    def can_retry(self, now: float) -> bool:
        self._evict(now)
        if len(self._requests) < self.min_requests:
            return True
        return (len(self._retries) / len(self._requests)) <= self.ratio


# INV_01 -----------------------------------------------------------------
def test_inv_warmup_bypass_confirms() -> None:
    b = _BudgetModel(ratio=0.0, min_requests=10)
    # fewer than min_requests -> always allow (even with ratio=0)
    for t in range(5):
        b.record_request(float(t))
        b.record_retry(float(t))
    assert b.can_retry(10.0) is True


def test_inv_warmup_bypass_prevents() -> None:
    # After min_requests is crossed, warmup no longer bypasses.
    b = _BudgetModel(ratio=0.0, min_requests=3)
    for t in range(10):
        b.record_request(float(t))
        b.record_retry(float(t))
    assert b.can_retry(10.0) is False


def test_inv_warmup_bypass_under_failure() -> None:
    # Even if min_requests is absurdly high, the system never deadlocks.
    b = _BudgetModel(min_requests=10**9)
    assert b.can_retry(0.0) is True


# INV_02 -----------------------------------------------------------------
def test_inv_ratio_enforcement_confirms() -> None:
    b = _BudgetModel(ratio=0.5, min_requests=1)
    for t in range(10):
        b.record_request(float(t))
    # 4 retries / 10 requests = 0.4 <= 0.5 -> allowed
    for t in range(4):
        b.record_retry(float(t))
    assert b.can_retry(10.0) is True


def test_inv_ratio_enforcement_prevents() -> None:
    b = _BudgetModel(ratio=0.1, min_requests=1)
    for t in range(10):
        b.record_request(float(t))
    for t in range(5):  # 50% retry rate
        b.record_retry(float(t))
    assert b.can_retry(10.0) is False


def test_inv_ratio_enforcement_under_failure() -> None:
    # ratio=0: any retry in warm state forbids further retries
    b = _BudgetModel(ratio=0.0, min_requests=1)
    for t in range(5):
        b.record_request(float(t))
    b.record_retry(0.0)
    assert b.can_retry(5.0) is False


# INV_03 -----------------------------------------------------------------
def test_inv_window_eviction_confirms() -> None:
    b = _BudgetModel(ratio=0.0, window_s=10.0, min_requests=1)
    b.record_request(0.0); b.record_retry(0.0)
    # 20s later the old samples must be gone and budget restored.
    assert b.can_retry(100.0) is True


def test_inv_window_eviction_prevents() -> None:
    # A sample INSIDE the window MUST count.
    b = _BudgetModel(ratio=0.0, window_s=10.0, min_requests=1)
    for t in range(5):
        b.record_request(95.0 + t)
    b.record_retry(99.0)
    assert b.can_retry(100.0) is False


def test_inv_window_eviction_under_failure() -> None:
    # window_s=0 -> every sample instantly stale -> no history retained
    b = _BudgetModel(ratio=0.0, window_s=0.0, min_requests=1)
    b.record_request(0.0); b.record_retry(0.0)
    assert b.can_retry(0.01) is True
