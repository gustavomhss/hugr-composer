from __future__ import annotations
from enum import Enum


class RefundStatus(str, Enum):
    """Lifecycle status of a Stripe refund.

    Values:
        pending: Refund requested, awaiting Stripe confirmation.
        succeeded: Refund completed (confirmed via webhook).
        failed: Refund declined by Stripe.
    """
    pending = 'pending'
    succeeded = 'succeeded'
    failed = 'failed'
