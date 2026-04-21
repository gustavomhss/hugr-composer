"""Billing namespace — provider-agnostic subscription + webhook primitives.

Registered primitives live at ``core/venous/billing/<Name>/``; concrete
provider wiring (Stripe, Paddle, …) lives under
``core/venous/_adapters/<framework>/`` as thin adapters over this
namespace.
"""
