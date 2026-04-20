from __future__ import annotations


def validate_secrets_at_startup() -> None:
    """Raise RuntimeError when required secrets are missing or weak.

    Call this inside your FastAPI lifespan *before* accepting traffic.

    Raises:
        RuntimeError: When a required secret is empty or matches a
            known-weak pattern.
    """
    provider = get_secret_provider()
    errors: list[str] = []
    for name in _REQUIRED_SECRETS:
        value = provider.get(name)
        if not value:
            errors.append(f'{name}: missing')
            continue
        lower = value.lower()
        if any((weak in lower for weak in _WEAK_PATTERNS)):
            errors.append(f'{name}: weak/default value detected')
    if errors:
        raise RuntimeError('Secret validation failed — refusing to start:\n' + '\n'.join((f'  - {e}' for e in errors)))
    logger.info('secret_validation_passed', extra={'checked': _REQUIRED_SECRETS})
