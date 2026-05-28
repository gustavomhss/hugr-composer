from __future__ import annotations


class APICostEstimator:
    """Estimate cost of external API calls made during a request.

    Uses ``RequestContext.external_api_calls`` multiplied by
    *rate_per_call*.
    """
    component = 'api'

    def __init__(self, rate_per_call: float=0.0001) -> None:
        """Initialise with cost per external API call in USD."""
        self._rate = rate_per_call

    def estimate(self, ctx: RequestContext) -> float:
        """Return estimated external API cost in USD."""
        return ctx.external_api_calls * self._rate
