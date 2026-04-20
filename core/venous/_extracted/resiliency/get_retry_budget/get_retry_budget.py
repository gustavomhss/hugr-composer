from __future__ import annotations


def get_retry_budget(service: str, ratio: float=0.1, window_s: float=60.0, min_requests: int=10) -> RetryBudget:
    """Return (and lazily create) the shared RetryBudget for *service*.

    Args:
        service: Service name. Same name returns the same instance.
        ratio: Budget ratio passed on first creation.
        window_s: Window seconds passed on first creation.
        min_requests: Warm-up count passed on first creation.

    Returns:
        The global ``RetryBudget`` instance for *service*.
    """
    with _lock:
        if service not in _budgets:
            _budgets[service] = RetryBudget(service=service, ratio=ratio, window_s=window_s, min_requests=min_requests)
        return _budgets[service]
