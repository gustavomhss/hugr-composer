from __future__ import annotations
from typing import Any


class StripeBilling:
    """Thin wrapper around the Stripe SDK for subscription operations.

    All methods import the ``stripe`` module lazily inside their bodies
    so ``app.main`` can boot without the SDK installed.

    Attributes:
        None — stateless; API key is set on each SDK call.
    """

    def _get_stripe(self) -> Any:
        """Return the configured ``stripe`` module (lazy import).

        Returns:
            The ``stripe`` module with ``api_key`` set from settings.
        """
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    def create_customer(self, email: str, metadata: dict[str, str] | None=None) -> Any:
        """Create a Stripe Customer object.

        Args:
            email: Customer email address.
            metadata: Optional metadata dict to attach.

        Returns:
            Stripe Customer object.
        """
        stripe = self._get_stripe()
        return stripe.Customer.create(email=email, metadata=metadata or {})

    def create_subscription(self, customer_id: str, price_id: str, trial_period_days: int | None=None) -> Any:
        """Create a Stripe Subscription for the given customer and price.

        Args:
            customer_id: Stripe Customer id.
            price_id: Stripe Price id.
            trial_period_days: Optional trial period in days.

        Returns:
            Stripe Subscription object.
        """
        stripe = self._get_stripe()
        params: dict[str, Any] = {'customer': customer_id, 'items': [{'price': price_id}]}
        if trial_period_days:
            params['trial_period_days'] = trial_period_days
        return stripe.Subscription.create(**params)

    def cancel_subscription(self, stripe_subscription_id: str) -> Any:
        """Cancel a Stripe Subscription at period end.

        Args:
            stripe_subscription_id: Stripe Subscription id.

        Returns:
            Updated Stripe Subscription object.
        """
        stripe = self._get_stripe()
        return stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=True)

    def change_plan(self, stripe_subscription_id: str, new_price_id: str) -> Any:
        """Change the plan for an existing subscription with proration.

        Args:
            stripe_subscription_id: Stripe Subscription id.
            new_price_id: New Stripe Price id.

        Returns:
            Updated Stripe Subscription object.
        """
        stripe = self._get_stripe()
        sub = stripe.Subscription.retrieve(stripe_subscription_id)
        item_id = sub['items']['data'][0]['id']
        return stripe.Subscription.modify(stripe_subscription_id, items=[{'id': item_id, 'price': new_price_id}], proration_behavior='create_prorations')

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Any:
        """Verify and construct a Stripe webhook event.

        Args:
            payload: Raw request body bytes.
            sig_header: Value of the ``Stripe-Signature`` header.

        Returns:
            Verified Stripe Event object.

        Raises:
            Exception: If signature verification fails.
        """
        stripe = self._get_stripe()
        return stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
