from __future__ import annotations


def get_cedar_engine() -> 'CedarEngine':
    """Return the process-wide CedarEngine singleton.

    Loads policies on first call.  Returns a no-op engine when
    ``CEDAR_ENABLED`` is False so the app always starts cleanly.

    Returns:
        The global ``CedarEngine`` instance.
    """
    global _engine_singleton
    if _engine_singleton is None:
        from app.core.config import settings
        policy_dir = getattr(settings, 'CEDAR_POLICY_DIR', 'app/authz/policies')
        _engine_singleton = CedarEngine(policy_dir=policy_dir)
        _engine_singleton.load_policies()
    return _engine_singleton
