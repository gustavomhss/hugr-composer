from __future__ import annotations


def get_cost_tracker() -> CostTracker:
    """Return (and lazily initialise) the global CostTracker instance."""
    global _tracker
    if _tracker is None:
        from app.costs.estimators import APICostEstimator, DBQueryCostEstimator, S3CostEstimator
        from app.core.config import settings
        _tracker = CostTracker()
        _tracker.register(DBQueryCostEstimator(rate_per_query=getattr(settings, 'COST_DB_QUERY_RATE', 1e-05)))
        _tracker.register(S3CostEstimator(rate_per_gb=getattr(settings, 'COST_S3_PER_GB', 0.023)))
        _tracker.register(APICostEstimator(rate_per_call=getattr(settings, 'COST_API_CALL_RATE', 0.0001)))
    return _tracker
