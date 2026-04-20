from __future__ import annotations


def classify_route(path: str) -> str:
    """Map a URL path to a bulkhead group name.

    Args:
        path: URL path of the incoming request.

    Returns:
        Bulkhead group name: 'payments', 'analytics', or 'crud'.
    """
    if path.startswith(('/payments', '/billing', '/subscriptions', '/invoices')):
        return 'payments'
    if path.startswith(('/analytics', '/reports', '/exports', '/metrics')):
        return 'analytics'
    return 'crud'
