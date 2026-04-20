from __future__ import annotations


class DBQueryCostEstimator:
    """Estimate cost of database queries in a request.

    Uses ``RequestContext.db_query_count`` multiplied by
    *rate_per_query* (cost per individual query in USD).
    """
    component = 'db'

    def __init__(self, rate_per_query: float=1e-05) -> None:
        """Initialise with cost per DB query in USD."""
        self._rate = rate_per_query

    def estimate(self, ctx: RequestContext) -> float:
        """Return estimated DB cost in USD."""
        return ctx.db_query_count * self._rate
