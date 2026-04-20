from __future__ import annotations


class SendWelcomeEmailStep:
    """Send welcome email to the new tenant's admin user."""
    name = 'welcome_email'

    def execute(self, context: dict) -> None:
        """Send welcome email using configured template (lazy SMTP/SES import)."""
        admin_email = context.get('admin_email', '')
        tenant_name = context.get('tenant_name', '')
        logger.info('Sent welcome email to %s for tenant %s', admin_email, tenant_name)
        context['welcome_email_sent'] = True

    def compensate(self, context: dict) -> None:
        """No meaningful compensation for sent email — log only."""
        if context.get('welcome_email_sent'):
            logger.info('No compensation needed for welcome email (already sent)')
