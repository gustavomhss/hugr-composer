from __future__ import annotations
from collections import defaultdict
import time


class CostTracker:
    """Aggregate per-request cost estimates from registered estimators.

    Estimators are invoked in registration order; any exception from
    an estimator is caught and logged — it never propagates to callers.
    """

    def __init__(self) -> None:
        """Initialise tracker with empty estimator registry and history."""
        self._estimators: list[CostEstimatorProtocol] = []
        self._history: list[CostEstimate] = []
        self._max_history: int = 10000

    def register(self, estimator: CostEstimatorProtocol) -> None:
        """Register a cost estimator."""
        self._estimators.append(estimator)
        logger.debug('Registered cost estimator: %s', estimator.component)

    def estimate_request(self, ctx: RequestContext) -> CostEstimate:
        """Run all estimators against *ctx* and return an aggregate estimate."""
        estimate = CostEstimate(request_id=ctx.request_id, path=ctx.path, method=ctx.method)
        for estimator in self._estimators:
            try:
                cost = estimator.estimate(ctx)
                if estimator.component == 'db':
                    estimate.db_cost_usd += cost
                elif estimator.component == 's3':
                    estimate.s3_cost_usd += cost
                elif estimator.component == 'api':
                    estimate.api_cost_usd += cost
            except Exception as exc:
                logger.warning('Cost estimator %s failed: %s', estimator.component, exc)
        estimate.total_cost_usd = estimate.db_cost_usd + estimate.s3_cost_usd + estimate.api_cost_usd
        if len(self._history) >= self._max_history:
            self._history.pop(0)
        self._history.append(estimate)
        return estimate

    def get_history(self, limit: int=1000) -> list[CostEstimate]:
        """Return the most recent *limit* cost estimates."""
        return self._history[-limit:]

    def get_by_endpoint(self, top_n: int=10) -> list[dict]:
        """Return top-N endpoints by total estimated cost (descending)."""
        aggregated: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        for est in self._history:
            key = f'{est.method} {est.path}'
            aggregated[key] += est.total_cost_usd
            counts[key] += 1
        ranked = sorted(aggregated.items(), key=lambda kv: kv[1], reverse=True)
        return [{'endpoint': k, 'total_cost_usd': round(v, 6), 'request_count': counts[k], 'avg_cost_usd': round(v / counts[k], 6)} for k, v in ranked[:top_n]]

    def get_summary(self) -> dict:
        """Return daily/weekly/monthly cost totals."""
        now = time.time()
        day_s = 86400
        result = {'daily': 0.0, 'weekly': 0.0, 'monthly': 0.0}
        for est in self._history:
            age = now - est.timestamp
            if age <= day_s:
                result['daily'] += est.total_cost_usd
            if age <= day_s * 7:
                result['weekly'] += est.total_cost_usd
            if age <= day_s * 30:
                result['monthly'] += est.total_cost_usd
        return {k: round(v, 6) for k, v in result.items()}
