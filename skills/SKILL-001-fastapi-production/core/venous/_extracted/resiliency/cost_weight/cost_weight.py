from __future__ import annotations


def cost_weight(endpoint: str, weights: dict[str, int] | None=None) -> int:
    """Return the cost weight for *endpoint*.

    Higher weight = more quota consumed per request.
    Defaults to 1 when no explicit weight is configured.

    Args:
        endpoint: Route path (e.g. ``/api/v1/reports``).
        weights: Optional mapping of path prefix to weight.

    Returns:
        Integer cost weight (>= 1).
    """
    if not weights:
        return 1
    for prefix, w in weights.items():
        if endpoint.startswith(prefix):
            return max(1, w)
    return 1
