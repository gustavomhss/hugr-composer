from __future__ import annotations
from typing import Any


def get_stripe() -> Any:
    """Return the configured ``stripe`` SDK module.

    Imports the ``stripe`` package lazily, assigns the API key and
    version from ``settings``, and returns the module.  Callers should
    use the return value directly (e.g.
    ``stripe = get_stripe(); session = stripe.checkout.Session.create(...)``).

    Returns:
        The ``stripe`` module object with ``api_key`` and
        ``api_version`` configured from application settings.

    Raises:
        ModuleNotFoundError: If the ``stripe`` package is not installed.
    """
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    return stripe
