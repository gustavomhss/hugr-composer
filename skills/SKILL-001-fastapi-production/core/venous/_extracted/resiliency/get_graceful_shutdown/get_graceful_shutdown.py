from __future__ import annotations
import os


def get_graceful_shutdown() -> GracefulShutdown:
    """Return the global GracefulShutdown instance (created on first call).

    Reads ``SHUTDOWN_DRAIN_SECONDS`` and ``SHUTDOWN_TIMEOUT_SECONDS``
    from the environment for initial configuration.

    Returns:
        The singleton ``GracefulShutdown`` instance.
    """
    global _shutdown
    if _shutdown is None:
        _shutdown = GracefulShutdown(drain_seconds=float(os.getenv('SHUTDOWN_DRAIN_SECONDS', '5')), timeout_seconds=float(os.getenv('SHUTDOWN_TIMEOUT_SECONDS', '30')))
    return _shutdown
