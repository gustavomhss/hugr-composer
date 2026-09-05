"""Pure Python primitive: CreateAdminUserStep."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class CreateAdminUserStep:
    """Create the admin user for the new tenant."""
    name = 'create_admin'

    def execute(self, context: dict) -> None:
        """Create admin user and store admin_user_id in context."""
        tenant_id = context.get('tenant_id', 'unknown')
        admin_email = context.get('admin_email', 'admin@example.com')
        admin_user_id = str(uuid.uuid4())
        context['admin_user_id'] = admin_user_id
        logger.info('Created admin user id=%s email=%s tenant=%s', admin_user_id, admin_email, tenant_id)

    def compensate(self, context: dict) -> None:
        """Delete the created admin user."""
        admin_user_id = context.get('admin_user_id')
        if admin_user_id:
            logger.info('Compensating: removing admin user id=%s', admin_user_id)
            context.pop('admin_user_id', None)
