from __future__ import annotations
from typing import Protocol


class CostEstimatorProtocol(Protocol):
    """Protocol that all cost estimators must satisfy."""

    def estimate(self, ctx: RequestContext) -> float:
        """Return estimated cost in USD for the given request context."""
        ...

    @property
    def component(self) -> str:
        """Return a short label for this estimator (e.g. 'db', 's3')."""
        ...
