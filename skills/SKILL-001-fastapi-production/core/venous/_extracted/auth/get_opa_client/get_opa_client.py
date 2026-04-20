from __future__ import annotations


def get_opa_client() -> OPAClient:
    """FastAPI dependency that returns the configured OPA client singleton.

    Reads OPA_URL, OPA_POLICY_PATH, OPA_TIMEOUT_MS, OPA_FAIL_OPEN from
    app settings.  The client is constructed on every call; production code
    should cache via ``lru_cache`` or an app-level lifespan store if needed.

    Returns:
        Configured ``OPAClient`` instance.
    """
    from app.core.config import settings
    return OPAClient(opa_url=getattr(settings, 'OPA_URL', 'http://localhost:8181'), policy_path=getattr(settings, 'OPA_POLICY_PATH', _DEFAULT_POLICY_PATH), timeout_ms=int(getattr(settings, 'OPA_TIMEOUT_MS', 500)), fail_open=bool(getattr(settings, 'OPA_FAIL_OPEN', False)))
