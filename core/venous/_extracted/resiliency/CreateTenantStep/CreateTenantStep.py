from __future__ import annotations
import uuid


class CreateTenantStep:
    """Create the tenant record in the database."""
    name = 'create_tenant'

    def execute(self, context: dict) -> None:
        """Create a tenant record and store tenant_id in context."""
        tenant_id = str(uuid.uuid4())
        context['tenant_id'] = tenant_id
        logger.info('Created tenant id=%s name=%s', tenant_id, context.get('tenant_name'))

    def compensate(self, context: dict) -> None:
        """Delete the created tenant if it was stored in context."""
        tenant_id = context.get('tenant_id')
        if tenant_id:
            logger.info('Compensating: removing tenant id=%s', tenant_id)
            context.pop('tenant_id', None)
