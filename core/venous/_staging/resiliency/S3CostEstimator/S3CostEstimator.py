from __future__ import annotations


class S3CostEstimator:
    """Estimate cost of S3/blob-storage transfers in a request.

    Uses ``RequestContext.s3_bytes_transferred`` converted to GB
    and multiplied by *rate_per_gb*.
    """
    component = 's3'

    def __init__(self, rate_per_gb: float=0.023) -> None:
        """Initialise with cost per GB transferred in USD."""
        self._rate = rate_per_gb

    def estimate(self, ctx: RequestContext) -> float:
        """Return estimated S3 cost in USD."""
        gb = ctx.s3_bytes_transferred / 1024 ** 3
        return gb * self._rate
