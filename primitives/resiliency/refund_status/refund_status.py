from __future__ import annotations
"""Pure Python primitive: RefundStatus."""

from enum import Enum

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

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
