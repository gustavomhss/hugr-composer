from __future__ import annotations


class SeedDataStep:
    """Seed initial data for the new tenant."""
    name = 'seed_data'

    def execute(self, context: dict) -> None:
        """Insert default tenant data (categories, settings, etc.)."""
        tenant_id = context.get('tenant_id', 'unknown')
        logger.info('Seeded default data for tenant=%s', tenant_id)
        context['seed_completed'] = True

    def compensate(self, context: dict) -> None:
        """Remove seeded data for the tenant."""
        if context.get('seed_completed'):
            logger.info('Compensating: removing seeded data for tenant=%s', context.get('tenant_id'))
            context.pop('seed_completed', None)
