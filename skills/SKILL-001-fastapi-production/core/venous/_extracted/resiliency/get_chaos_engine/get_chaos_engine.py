from __future__ import annotations
import os


def get_chaos_engine() -> ChaosEngine:
    """Return the global ChaosEngine instance, creating it on first call.

    Reads ``CHAOS_LATENCY_MS``, ``CHAOS_ERROR_RATE``, and
    ``CHAOS_TIMEOUT_RATE`` from the environment for initial configuration.

    Returns:
        The singleton ``ChaosEngine`` instance.
    """
    global _engine
    if _engine is None:
        _engine = ChaosEngine(latency_ms=int(os.getenv('CHAOS_LATENCY_MS', '0')), error_rate=float(os.getenv('CHAOS_ERROR_RATE', '0.0')), timeout_rate=float(os.getenv('CHAOS_TIMEOUT_RATE', '0.0')))
        if os.getenv('CHAOS_ENABLED', 'false').lower() == 'true':
            _engine.enable()
    return _engine
