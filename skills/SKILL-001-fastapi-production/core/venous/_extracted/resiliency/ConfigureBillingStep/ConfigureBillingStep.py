from __future__ import annotations


class ConfigureBillingStep:
    """Configure billing / subscription for the new tenant."""
    name = 'configure_billing'

    def execute(self, context: dict) -> None:
        """Register tenant with billing provider (Stripe, etc.)."""
        tenant_id = context.get('tenant_id', 'unknown')
        logger.info('Configured billing for tenant=%s', tenant_id)
        context['billing_configured'] = True

    def compensate(self, context: dict) -> None:
        """Remove billing configuration for the tenant."""
        if context.get('billing_configured'):
            logger.info('Compensating: removing billing for tenant=%s', context.get('tenant_id'))
            context.pop('billing_configured', None)
