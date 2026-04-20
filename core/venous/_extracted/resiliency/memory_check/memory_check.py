from __future__ import annotations
import time


async def memory_check() -> DependencyCheck:
    """Check process RSS against a configured threshold.

    Marks check as ``unhealthy`` when RSS exceeds
    ``HEALTH_MEMORY_THRESHOLD_MB`` (default 512 MB).

    Returns:
        DependencyCheck with ``rss_mb``, ``vms_mb``, and
        ``threshold_mb`` in ``details``.
    """
    t0 = time.monotonic()
    try:
        import os as _os
        import psutil
        threshold_mb = int(_os.getenv('HEALTH_MEMORY_THRESHOLD_MB', '512'))
        proc = psutil.Process()
        mem = proc.memory_info()
        rss_mb = round(mem.rss / 1048576, 2)
        vms_mb = round(mem.vms / 1048576, 2)
        details = {'rss_mb': rss_mb, 'vms_mb': vms_mb, 'threshold_mb': threshold_mb}
        status = HealthStatus.UNHEALTHY if rss_mb >= threshold_mb else HealthStatus.HEALTHY
        latency = int((time.monotonic() - t0) * 1000)
        return DependencyCheck(name='memory', status=status, latency_ms=latency, details=details)
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning('Memory health check failed: %s', exc)
        return DependencyCheck(name='memory', status=HealthStatus.UNHEALTHY, latency_ms=latency, details={'error': str(exc)})
