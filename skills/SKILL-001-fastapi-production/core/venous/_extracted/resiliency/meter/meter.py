from __future__ import annotations


def meter(meter_name: str, *, cost_unit: str, per: int=1, path_prefix: str='/api', stripe_meter_id: str='', enabled: bool=True) -> MeteringRule:
    """Register a metering rule in the global registry.

    Args:
        meter_name: Logical name for the meter (matches Stripe meter).
        cost_unit: Unit of measure (e.g. ``"token"``, ``"request"``).
        per: How many units per single rule invocation.
        path_prefix: Only paths starting with this prefix are metered.
        stripe_meter_id: Optional Stripe Meter ID for direct event submission.
        enabled: Set False to disable without deleting the rule.

    Returns:
        The registered ``MeteringRule`` instance.
    """
    rule = MeteringRule(meter_name=meter_name, cost_unit=cost_unit, per=per, path_prefix=path_prefix, stripe_meter_id=stripe_meter_id, enabled=enabled)
    _RULES.append(rule)
    logger.debug('Registered metering rule: %s', meter_name)
    return rule
