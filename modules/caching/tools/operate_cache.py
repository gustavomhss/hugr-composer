"""
SKILL-001 Caching Tool: Runtime cache health diagnostics.

Connects to a live Redis instance and reports memory usage, hit/miss rates,
eviction counts, connected clients, key distribution, and latency. Designed
to be called as an operational tool for live monitoring and diagnostics.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_resiliency_operate_cache',
    'description': 'Check runtime Redis cache health: memory usage, hit/miss rates, evictions, connected clients, key distribution, latency.',
    'tags': ['caching', 'resiliency', 'operate'],
    'entry': 'check_cache_health',
    'annotations': {'readOnlyHint': True, 'destructiveHint': False},
}

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Thresholds for health assessment
_MAX_MEMORY_USAGE_PCT = 85.0  # Alert when memory usage exceeds 85%
_MIN_HIT_RATE = 0.80           # Alert when hit rate drops below 80%
_MAX_EVICTIONS_PER_HOUR = 1000 # Alert on high eviction rate
_MAX_LATENCY_MS = 5.0          # Alert when latency exceeds 5ms


def check_cache_health(redis_url: str = "redis://localhost:6379") -> dict:
    """
    Check the health of a live Redis cache instance.

    Connects to the Redis instance and collects key performance metrics:
    memory usage, hit/miss rates, eviction counts, connected clients,
    key namespace distribution, and round-trip latency.

    This function uses the synchronous ``redis`` client to avoid requiring
    an async context. For integration in FastAPI, wrap in
    ``asyncio.to_thread(check_cache_health, url)``.

    Args:
        redis_url: Redis connection URL (e.g., "redis://localhost:6379").

    Returns:
        Dict with keys:
            - ``status``: "healthy", "degraded", or "unhealthy"
            - ``memory``: Memory usage stats
            - ``performance``: Hit rate, latency, ops/sec
            - ``keys``: Key count and namespace distribution
            - ``clients``: Connected client info
            - ``findings``: List of Finding objects for detected issues

    Example::

        result = check_cache_health("redis://localhost:6379")
        print(f"Status: {result['status']}")
        print(f"Hit rate: {result['performance']['hit_rate']:.1%}")
        print(f"Memory: {result['memory']['used_human']}")
        for f in result['findings']:
            print(f"  [{f.severity.value}] {f.title}")
    """
    try:
        import redis as sync_redis
    except ImportError:
        return {
            "status": "error",
            "error": "redis package not installed. Run: pip install redis",
            "findings": [Finding(
                rule_id="CACHE-HEALTH-00",
                severity=Severity.HIGH,
                title="Cannot check cache health: redis package not installed",
                description="The redis Python package is required for health checks.",
                fix_suggestion="pip install redis",
            )],
        }

    findings: list[Finding] = []

    try:
        client = sync_redis.from_url(redis_url, decode_responses=True)

        # --- Latency ---
        start = time.monotonic()
        client.ping()
        latency_ms = (time.monotonic() - start) * 1000

        if latency_ms > _MAX_LATENCY_MS:
            findings.append(Finding(
                rule_id="CACHE-HEALTH-01",
                severity=Severity.MEDIUM,
                title=f"Redis latency is high: {latency_ms:.1f}ms",
                description=(
                    f"Redis ping latency is {latency_ms:.1f}ms (threshold: "
                    f"{_MAX_LATENCY_MS}ms). High latency impacts every cache "
                    f"operation. Common causes: network distance, Redis overload, "
                    f"or insufficient server resources."
                ),
                fix_suggestion=(
                    "Check network path to Redis. Consider running Redis on "
                    "localhost or in the same availability zone."
                ),
            ))

        # --- Server info ---
        info = client.info()

        # --- Memory ---
        used_memory = info.get("used_memory", 0)
        max_memory = info.get("maxmemory", 0)
        used_human = info.get("used_memory_human", "unknown")
        peak_human = info.get("used_memory_peak_human", "unknown")
        evicted_keys = info.get("evicted_keys", 0)
        memory_policy = info.get("maxmemory_policy", "noeviction")

        memory_pct = 0.0
        if max_memory > 0:
            memory_pct = (used_memory / max_memory) * 100

            if memory_pct > _MAX_MEMORY_USAGE_PCT:
                findings.append(Finding(
                    rule_id="CACHE-HEALTH-02",
                    severity=Severity.HIGH,
                    title=f"Redis memory usage critical: {memory_pct:.1f}%",
                    description=(
                        f"Redis is using {memory_pct:.1f}% of maxmemory "
                        f"({used_human} / {max_memory} bytes). Eviction policy: "
                        f"{memory_policy}. High memory usage causes evictions "
                        f"(cache thrashing) or OOM errors if policy is noeviction."
                    ),
                    fix_suggestion=(
                        "Increase maxmemory, reduce TTLs, or audit keys for "
                        "unnecessary large values. Consider allkeys-lru eviction "
                        "policy if not already set."
                    ),
                ))
        else:
            findings.append(Finding(
                rule_id="CACHE-HEALTH-03",
                severity=Severity.LOW,
                title="Redis maxmemory not configured",
                description=(
                    "maxmemory is not set. Redis will use all available system "
                    "memory, which can cause the OS to OOM-kill the Redis process."
                ),
                fix_suggestion=(
                    "Set maxmemory in redis.conf (e.g., maxmemory 512mb) and "
                    "configure an eviction policy (e.g., allkeys-lru)."
                ),
            ))

        if evicted_keys > 0:
            findings.append(Finding(
                rule_id="CACHE-HEALTH-04",
                severity=Severity.MEDIUM if evicted_keys > _MAX_EVICTIONS_PER_HOUR else Severity.LOW,
                title=f"Redis has evicted {evicted_keys} keys",
                description=(
                    f"Redis has evicted {evicted_keys} keys due to memory pressure. "
                    f"Evictions mean cache entries are being removed before their "
                    f"TTL expires, reducing cache effectiveness."
                ),
                fix_suggestion=(
                    "Increase maxmemory or reduce the amount of data cached. "
                    "Review TTLs — shorter TTLs reduce memory pressure."
                ),
            ))

        # --- Performance ---
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        hit_rate = (hits / total) if total > 0 else 0.0
        ops_per_sec = info.get("instantaneous_ops_per_sec", 0)

        if total > 100 and hit_rate < _MIN_HIT_RATE:
            findings.append(Finding(
                rule_id="CACHE-HEALTH-05",
                severity=Severity.MEDIUM,
                title=f"Cache hit rate is low: {hit_rate:.1%}",
                description=(
                    f"Cache hit rate is {hit_rate:.1%} ({hits} hits / "
                    f"{misses} misses). A healthy cache should have > 80% "
                    f"hit rate. Low hit rate means most requests bypass cache "
                    f"and hit the database directly."
                ),
                fix_suggestion=(
                    "Check if cache keys are correct, TTLs are long enough, "
                    "and cache warming is running on deploy. Audit cache "
                    "invalidation — too-aggressive invalidation reduces hits."
                ),
            ))

        # --- Clients ---
        connected_clients = info.get("connected_clients", 0)
        max_clients = info.get("maxclients", 10000)
        blocked_clients = info.get("blocked_clients", 0)

        if connected_clients > max_clients * 0.8:
            findings.append(Finding(
                rule_id="CACHE-HEALTH-06",
                severity=Severity.HIGH,
                title=f"Redis client connections near limit: {connected_clients}/{max_clients}",
                description=(
                    f"Redis has {connected_clients} connected clients out of "
                    f"max {max_clients}. Approaching the limit causes connection "
                    f"refused errors."
                ),
                fix_suggestion=(
                    "Review connection pool sizes in all applications. Use "
                    "connection pooling (max_connections=20 per app instance)."
                ),
            ))

        # --- Key distribution ---
        db_info = {}
        total_keys = 0
        for key, value in info.items():
            if key.startswith("db") and isinstance(value, dict):
                keys_count = value.get("keys", 0)
                db_info[key] = keys_count
                total_keys += keys_count

        # --- Namespace distribution (sample-based) ---
        namespaces: dict[str, int] = {}
        try:
            sample_count = 0
            for key in client.scan_iter(match="*", count=100):
                prefix = key.split(":")[0] if ":" in key else "_no_namespace"
                namespaces[prefix] = namespaces.get(prefix, 0) + 1
                sample_count += 1
                if sample_count >= 500:  # Cap sampling
                    break
        except Exception:
            pass  # Sampling is best-effort

        # --- Status ---
        severity_counts = {s: 0 for s in Severity}
        for f in findings:
            severity_counts[f.severity] += 1

        if severity_counts[Severity.CRITICAL] > 0:
            status = "unhealthy"
        elif severity_counts[Severity.HIGH] > 0 or severity_counts[Severity.MEDIUM] > 0:
            status = "degraded"
        else:
            status = "healthy"

        client.close()

        return {
            "status": status,
            "memory": {
                "used_human": used_human,
                "used_bytes": used_memory,
                "peak_human": peak_human,
                "max_memory": max_memory,
                "usage_pct": round(memory_pct, 1),
                "eviction_policy": memory_policy,
                "evicted_keys": evicted_keys,
            },
            "performance": {
                "hit_rate": round(hit_rate, 4),
                "hits": hits,
                "misses": misses,
                "ops_per_sec": ops_per_sec,
                "latency_ms": round(latency_ms, 2),
            },
            "keys": {
                "total": total_keys,
                "databases": db_info,
                "namespace_sample": dict(
                    sorted(namespaces.items(), key=lambda x: -x[1])[:20]
                ),
            },
            "clients": {
                "connected": connected_clients,
                "max": max_clients,
                "blocked": blocked_clients,
            },
            "findings": findings,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": f"Cannot connect to Redis at {redis_url}: {exc}",
            "findings": [Finding(
                rule_id="CACHE-HEALTH-00",
                severity=Severity.CRITICAL,
                title=f"Cannot connect to Redis: {exc}",
                description=(
                    f"Failed to connect to Redis at {redis_url}. "
                    f"The cache layer is completely non-functional."
                ),
                fix_suggestion=(
                    "Check that Redis is running and accessible. Verify the "
                    "connection URL, port, and any authentication requirements."
                ),
            )],
        }
