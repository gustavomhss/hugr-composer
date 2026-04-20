from __future__ import annotations


def build_config() -> AdaptiveThrottleConfig:
    """Build AdaptiveThrottleConfig from current settings.

    Returns:
        AdaptiveThrottleConfig populated from ADAPTIVE_THROTTLE_* fields.
    """
    redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0') or ''
    return AdaptiveThrottleConfig(enabled=settings.ADAPTIVE_THROTTLE_ENABLED, sensitivity=settings.ADAPTIVE_THROTTLE_SENSITIVITY, learning_period_h=settings.ADAPTIVE_THROTTLE_LEARNING_PERIOD_H, base_quota=settings.ADAPTIVE_THROTTLE_BASE_QUOTA, penalty_escalation=settings.ADAPTIVE_THROTTLE_PENALTY_ESCALATION, redis_url=str(redis_url))
