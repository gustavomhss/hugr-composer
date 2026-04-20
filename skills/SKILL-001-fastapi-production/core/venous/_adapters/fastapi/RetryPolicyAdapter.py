"""FastAPI adapter over the `RetryPolicy` primitive.

Exposes a shared ``ExponentialBackoffRetryPolicy`` on ``app.state`` and a
``Depends``-compatible accessor so route handlers can wrap external calls
with backoff + retry budget + TimeoutBudget in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI, Depends
    from core.venous._adapters.fastapi.RetryPolicyAdapter import install, policy_dep

    app = FastAPI()
    install(app, max_attempts=3, initial_interval_ms=100)

    @app.get("/upstream")
    async def read(p=Depends(policy_dep)):
        return await p.execute(lambda: call_upstream(), idempotent=True)
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from core.venous.resiliency.RetryPolicy.RetryPolicy import (
    ExponentialBackoffRetryPolicy,
    TimeoutBudget,
)


def install(
    app: FastAPI,
    *,
    max_attempts: int = 3,
    initial_interval_ms: int = 100,
    multiplier: float = 2.0,
    max_interval_ms: int = 30_000,
    jitter: float = 1.0,
    budget_ratio: float = 0.1,
    requires_idempotency: bool = True,
) -> ExponentialBackoffRetryPolicy:
    """Install a shared retry policy on *app*; return the live primitive."""
    policy = ExponentialBackoffRetryPolicy(
        max_attempts=max_attempts,
        initial_interval_ms=initial_interval_ms,
        multiplier=multiplier,
        max_interval_ms=max_interval_ms,
        jitter=jitter,
        budget_ratio=budget_ratio,
        requires_idempotency=requires_idempotency,
    )
    app.state.retry_policy = policy
    return policy


def policy_dep(request: Request) -> ExponentialBackoffRetryPolicy:
    """FastAPI ``Depends``-compatible accessor for the installed policy."""
    return request.app.state.retry_policy


def budget(remaining_ms: int) -> TimeoutBudget:
    """Shorthand for constructing a per-request :class:`TimeoutBudget`."""
    return TimeoutBudget(remaining_ms=remaining_ms)
