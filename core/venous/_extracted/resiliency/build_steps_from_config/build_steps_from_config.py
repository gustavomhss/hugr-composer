from __future__ import annotations


def build_steps_from_config(steps_config: str) -> list:
    """Build a list of step instances from a comma-separated config string.

    Args:
        steps_config: Comma-separated step names, e.g.
            ``"create_tenant,create_admin,seed_data"``.

    Returns:
        List of instantiated step objects in the configured order.
    """
    names = [s.strip() for s in steps_config.split(',') if s.strip()]
    steps = []
    for name in names:
        cls = _STEP_REGISTRY.get(name)
        if cls is None:
            logger.warning('Unknown onboarding step: %s — skipped', name)
            continue
        steps.append(cls())
    return steps
