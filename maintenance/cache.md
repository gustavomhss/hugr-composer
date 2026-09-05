# Cache Domain — Maintenance Skill

> **Crates**: 3 (`KeyValueBucket`, `DistributedLock`, `SessionCache`) | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Distributed caching, locking, and session management — the backbone of horizontal scaling.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `KeyValueBucket` | Generic distributed key-value store with TTL | Medium | Production |
| `DistributedLock` | Redis-based distributed mutex with TTL/auto-release | High | Production |
| `SessionCache` | Session storage with automatic TTL/cleanup | Medium | Production |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CACHE LAYER                          │
├─────────────────────────────────────────────────────────────┤
│  App → KeyValueBucket → Redis Cluster                       │
│       ↓                                                      │
│  DistributedLock → Redis (SET NX + Lua)                     │
│       ↓                                                      │
│  SessionCache → Redis (TTL + automatic cleanup)             │
└─────────────────────────────────────────────────────────────┘
```

---

## Crate Details

### 1. `KeyValueBucket`

**Location**: `core/venous/cache/KeyValueBucket/`

**Purpose**: Generic distributed key-value store with TTL, namespacing, and atomic operations.

**Key Features**:
- Namespace isolation (prevents key collisions)
- TTL with automatic expiration
- Atomic operations (get, set, delete, exists, increment)
- Batch operations (mget, mset, mdelete)
- TTL extension/renewal

**Key Interfaces**:
```python
class KeyValueBucket(Protocol):
    async def get(self, key: str) -> bytes | None
    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None
    async def delete(self, key: str) -> bool
    async def exists(self, key: str) -> bool
    async def increment(self, key: str, amount: int = 1) -> int
    async def mget(self, keys: list[str]) -> list[bytes | None]
    async def mset(self, mapping: dict[str, bytes], ttl: int | None = None) -> None
    async def mdelete(self, keys: list[str]) -> int
    async def ttl(self, key: str) -> int | None
    async def expire(self, key: str, ttl: int) -> bool
```

---

### 2. `DistributedLock`

**Location**: `core/venous/cache/DistributedLock/`

**Purpose**: Redis-based distributed mutex with automatic expiration and Lua-scripted atomic operations.

**Key Features**:
- Lua-scripted atomic acquire/release (prevents race conditions)
- Automatic expiration (TTL) prevents deadlocks
- Lock extension/renewal for long operations
- Lock metadata (owner, acquired_at, expires_at)
- Reentrant support (same owner can re-acquire)

**Key Interfaces**:
```python
class DistributedLock(Protocol):
    async def acquire(
        self,
        name: str,
        owner: str,
        ttl: int = 30,
        blocking: bool = True,
        blocking_timeout: int = 10,
    ) -> bool
    
    async def release(self, name: str, owner: str) -> bool
    async def extend(self, name: str, owner: str, additional_ttl: int) -> bool
    async def get_lock_info(self, name: str) -> LockInfo | None
    async def force_release(self, name: str) -> bool  # Admin only
```

**LockInfo**:
```python
@dataclass
class LockInfo:
    name: str
    owner: str
    acquired_at: datetime
    expires_at: datetime
    is_expired: bool
```

---

### 3. `SessionCache`

**Location**: `core/venous/cache/SessionCache/`

**Purpose**: High-performance session storage with automatic TTL management and cleanup.

**Key Features**:
- Automatic TTL management (sliding window)
- Session data compression (optional, for large sessions)
- Automatic cleanup of expired sessions
- Session metadata (created_at, last_accessed, ip, user_agent)
- Session invalidation (logout, admin revoke)

**Key Interfaces**:
```python
class SessionCache(Protocol):
    async def create(
        self,
        user_id: str,
        data: dict,
        ttl: int = 86400,  # 24h default
        metadata: dict | None = None,
    ) -> str  # returns session_id
    
    async def get(self, session_id: str) -> SessionData | None
    async def update(self, session_id: str, data: dict, extend_ttl: bool = True) -> bool
    async def delete(self, session_id: str) -> bool
    async def exists(self, session_id: str) -> bool
    async def touch(self, session_id: str, ttl: int | None = None) -> bool
    async def delete_user_sessions(self, user_id: str) -> int  # logout all devices
    async def cleanup_expired(self) -> int  # returns count of cleaned sessions
```

---

## Common Operations

### 1. Using Distributed Locks Safely

```python
# ✅ CORRECT: Always use try/finally
lock = distributed_lock.acquire("resource-name", owner="worker-1", ttl=30)
try:
    if not lock:
        raise LockAcquisitionError("Could not acquire lock")
    # Critical section
    await do_critical_work()
finally:
    await distributed_lock.release("resource-name", owner="worker-1")

# ❌ WRONG: Forgetting to release
lock = await distributed_lock.acquire("resource-name", owner="worker-1")
await do_critical_work()
# Lock never released! → deadlock
```

### 2. Using KeyValueBucket with Namespaces

```python
# Always use namespaces to prevent collisions
bucket = KeyValueBucket(namespace="user:sessions")

# Keys are automatically prefixed: "user:sessions:user:123:profile"
await bucket.set("user:123:profile", b'{"name": "John"}', ttl=3600)
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Lock not released** | Deadlock, all workers stuck | Always use `try/finally` or context manager |
| **Lock TTL too short** | Lock expires mid-operation | Set TTL > max expected operation time + buffer |
| **Lock contention** | High latency, timeouts | Reduce critical section; use finer-grained locks |
| **Cache stampede** | Thundering herd on cache miss | Use `DistributedLock` + `KeyValueBucket` for cache warming |
| **Session fixation** | Attacker fixes session ID | Regenerate session ID on login |
| **Session hijacking** | Stolen session used | Bind session to IP/User-Agent; rotate on privilege change |
| **Cache stampede on cold start** | All workers hit DB simultaneously | Use `DistributedLock` for cache warming |
| **Memory leak** | Sessions never cleaned | Ensure `SessionCache.cleanup_expired()` runs periodically |

---


## Evolution Without Breaking Contracts

### Adding New Fields to Session Data

```python
# Sessions store arbitrary JSON — just add fields
session_data = {
    "user_id": "123",
    "roles": ["user"],
    "preferences": {"theme": "dark"},  # NEW FIELD
}
# Consumers use .get("preferences") — safe
```

### Changing Session TTL

```python
# Non-breaking: TTL is per-session, configurable per-create
await session_cache.create(user_id, data, ttl=86400)  # 24h
await session_cache.create(user_id, data, ttl=604800)  # 7 days for "remember me"
```

---


## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing lock algorithm | **REVIEW** — Correctness critical |
| Changing session serialization format | **STOP** — Migration plan required |
| Changing TTL defaults | **REVIEW** — Impact on UX/security |
| Adding new lock types | **REVIEW** — Deadlock risk |
| Changing session serialization | **STOP** — Migration plan required |

---

## Health Checks & Monitoring

```python
@app.get("/health/cache")
async def cache_health():
    return {
        "status": "healthy",
        "checks": {
            "redis_ping": await redis.ping(),
            "lock_acquisition": await test_lock_acquisition(),
            "session_store": await session_cache.ping(),
            "cleanup_job": await check_cleanup_job(),
        }
    }

# Metrics to alert on:
# - cache.hit_rate < 80%
# - lock.acquisition.latency.p99 > 100ms
# - lock.contention_rate > 10%
# - session.cache.hit_rate < 90%
# - session.cleanup.duration > 60s
```

---

## Debugging Quick Reference

```bash
# Check Redis connection
redis-cli PING

# Inspect lock
redis-cli GET "lock:resource-name"

# Inspect session
redis-cli GET "session:<session_id>"

# Check lock contention
redis-cli --scan --pattern "lock:*" | xargs -I {} sh -c 'echo -n "{} "; redis-cli TTL {}'

# List all sessions for user
redis-cli KEYS "session:user:123:*"

# Force release stuck lock (admin only)
redis-cli DEL "lock:stuck-resource"

# Check TTLs
redis-cli --scan --pattern "session:*" | xargs -I {} sh -c 'echo -n "{} "; redis-cli TTL {}'
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Redis connection pool | `max_connections` | 50-100 |
| Lock TTL | Default TTL | 30s (adjust per use case) |
| Session TTL | Default | 24h (access) / 30d (refresh) |
| Redis pipeline | Batch size | 100-500 |
| Connection pool | Max idle | 10 |

---

## Security Checklist

- [ ] All lock operations use Lua scripts (atomic)
- [ ] Lock ownership verified on release
- [ ] Session IDs are cryptographically random (256-bit)
- [ ] Session IDs rotated on privilege change
- [ ] Session data encrypted at rest (if sensitive)
- [ ] Session cookies: `Secure; HttpOnly; SameSite=Lax`
- [ ] Session TTL configurable per-use-case
- [ ] Admin session revocation works
- [ ] Lock force-release requires admin auth
- [ ] Cache keys don't leak sensitive data

---

*Cache Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*