from __future__ import annotations
import os
import time


async def disk_check() -> DependencyCheck:
    """Check available disk space against a configured threshold.

    Uses ``psutil.disk_usage`` on the filesystem root.  Marks check as
    ``unhealthy`` when used percentage exceeds
    ``HEALTH_DISK_THRESHOLD_PCT`` (default 90 %).

    Returns:
        DependencyCheck with ``total_gb``, ``used_pct``, and ``free_gb``
        in ``details``.
    """
    t0 = time.monotonic()
    try:
        import psutil
        threshold = int(os.getenv('HEALTH_DISK_THRESHOLD_PCT', '90'))
        usage = psutil.disk_usage('/')
        used_pct = usage.percent
        details = {'total_gb': round(usage.total / 1073741824, 2), 'used_pct': used_pct, 'free_gb': round(usage.free / 1073741824, 2), 'threshold_pct': threshold}
        status = HealthStatus.UNHEALTHY if used_pct >= threshold else HealthStatus.HEALTHY
        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(name='disk', status=status, latency_ms=latency, details=details)
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning('Disk health check failed: %s', exc)
        return DependencyCheck(name='disk', status=HealthStatus.UNHEALTHY, latency_ms=latency, details={'error': str(exc)})
