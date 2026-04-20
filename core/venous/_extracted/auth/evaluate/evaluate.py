from __future__ import annotations


def evaluate(toggle: object, *, user_id: str | None=None, environment: str='production') -> tuple[bool, str]:
    """Evaluate whether a toggle is active for a given context.

    Uses percentage rollout via ``hash(user_id + toggle.name) % 100``
    which is fully deterministic — the same user always gets the same
    bucket for a given toggle name.

    Args:
        toggle: FeatureToggle ORM instance (duck-typed for testability).
        user_id: Optional user identifier string for bucketing.
        environment: Current runtime environment string.

    Returns:
        Tuple of (enabled: bool, reason: str).
    """
    if not toggle.enabled:
        return (False, 'disabled')
    if user_id and user_id in (toggle.allowed_users or []):
        return (True, 'allowlist')
    envs = toggle.environments or []
    if envs and environment not in envs:
        return (False, 'environment_gate')
    pct = toggle.rollout_percentage
    if pct >= 100:
        return (True, 'full_rollout')
    if pct <= 0:
        return (False, 'zero_rollout')
    if user_id:
        bucket = _bucket(toggle.name, user_id)
        if bucket < pct:
            return (True, f'rollout:{pct}%')
        return (False, f'rollout:{pct}%')
    return (False, 'no_user_id')
