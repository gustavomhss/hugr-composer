"""Stripe adapters — framework glue for the Stripe Python SDK.

Exposes:

- ``StripeBillingAdapter`` — implements the ``billing.Billing`` Protocol
  against the Stripe SDK. Lazy-imports ``stripe`` so a FastAPI app boots
  without the SDK installed; raises ``StripeNotInstalled`` only when a
  billing call actually needs the client.

All domain invariants (BILL_INV_01..05) are enforced by the motor
contract; this adapter is thin provider glue.
"""
from core.venous._adapters.stripe.BillingAdapter import (
    StripeBillingAdapter,
    StripeNotInstalled,
)

__all__ = [
    "StripeBillingAdapter",
    "StripeNotInstalled",
]
