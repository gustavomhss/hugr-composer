from __future__ import annotations
import os


def get_default_config() -> BulkheadConfig:
    """Return BulkheadConfig populated from environment variables.

    Reads:
        BULKHEAD_PAYMENTS_MAX  (default 10)
        BULKHEAD_CRUD_MAX      (default 50)
        BULKHEAD_ANALYTICS_MAX (default 20)

    Returns:
        ``BulkheadConfig`` with per-group limits.
    """
    return BulkheadConfig(limits={'payments': int(os.getenv('BULKHEAD_PAYMENTS_MAX', '10')), 'crud': int(os.getenv('BULKHEAD_CRUD_MAX', '50')), 'analytics': int(os.getenv('BULKHEAD_ANALYTICS_MAX', '20'))})
