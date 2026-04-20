from __future__ import annotations


def dispatch_usage_alert(tenant_id: str, threshold_pct: int, quota: TenantQuota) -> None:
    """Fire a usage alert webhook when a quota threshold is crossed.

    Args:
        tenant_id: Tenant whose quota threshold was crossed.
        threshold_pct: The threshold percentage that was reached (80/90/100).
        quota: The ``TenantQuota`` object with usage details.
    """
    from app.core.config import settings
    webhook_url = getattr(settings, 'USAGE_ALERT_WEBHOOK_URL', '')
    if not webhook_url:
        logger.info('Usage alert %d%% for tenant %s (no webhook configured)', threshold_pct, tenant_id)
        return
    try:
        import httpx
        payload = {'tenant_id': tenant_id, 'threshold_pct': threshold_pct, 'current_usage': quota.current_usage, 'monthly_limit': quota.monthly_limit, 'tier': quota.tier}
        httpx.post(webhook_url, json=payload, timeout=5.0)
        logger.info('Usage alert dispatched: tenant=%s threshold=%d%%', tenant_id, threshold_pct)
    except Exception as exc:
        logger.warning('Failed to dispatch usage alert: %s', exc)
