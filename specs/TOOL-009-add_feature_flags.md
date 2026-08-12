---
spec_id: "TOOL-009"
tool_name: "add_feature_flags"
primitive: "auth/FeatureFlagCache"
primitive_path: "core.venous.auth.FeatureFlagCache"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-FF-01"
  - "INV-FF-02"
  - "INV-FF-03"
  - "INV-FF-04"
  - "INV-FF-05"
  - "INV-FF-06"
  - "INV-FF-07"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-009: add_feature_flags

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_feature_flags` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User), Redis (for pubsub invalidation), Alembic |
| Signature | `add_feature_flags(project_dir: str, with_admin_ui: bool = False, cache_ttl_seconds: int = 60, evaluator_timeout_ms: int = 5) -> dict` |
| Parameters | `project_dir`: project root path<br>`with_admin_ui`: also generate basic admin endpoints (CRUD on flags)<br>`cache_ttl_seconds`: in-process cache TTL<br>`evaluator_timeout_ms`: hard cap on flag evaluation latency (used by circuit breaker) |

---

## 2. Purpose

Add a production-grade feature-flag system that allows enabling, disabling, or bucketing features per user, per tenant, per environment, or for a configurable percentage of traffic without ever requiring a redeploy. The system supports boolean flags, multi-variant flags (A/B/n buckets with deterministic hash-based assignment so the same user always lands in the same bucket across requests), targeting rules (attribute equality, containment, regex), gradual percentage rollouts, emergency kill-switches that bypass all other evaluation logic, and a full audit trail of every flag change with actor, before state, after state, timestamp, and reason.

Flag evaluation is sub-millisecond via an in-process LRU cache invalidated by Redis pub/sub fan-out so multiple worker processes stay consistent within 50 ms of each other, eliminating the classic "one worker sees the new flag, another doesn't" race. Every flag mutation is recorded in a `feature_flag_audit` table for compliance and incident investigation. Design decisions: Redis for zero-latency reads, SQLAlchemy for durable config storage, deterministic SHA256 bucketing for rollout percentages, a pluggable context evaluator (user, tenant, environment, custom attributes), and admin endpoints protected by TOOL-012 RBAC so only authorized operators can touch production flags.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Dev waits in CLI |
| Files modified | ≤ 4 global files | Predictability |
| Files created | ≥ 8 (model, crud, routes, schemas, evaluator, cache, decorator, tests) | Predictability |
| Flag evaluation latency p99 | < 1 ms | Cached in-process; Redis miss path < 5 ms |
| Flag evaluation circuit breaker | 5 ms hard cap | Evaluator returns default on timeout, never blocks request |
| Cache hit ratio | > 99% in steady state | TTL=60s, invalidated on update via Redis pubsub |
| Update propagation | < 1s across N workers | Pubsub fan-out |
| Memory overhead | < 5 MB per worker | Bounded LRU cache (max 10k flags) |
| Migration runtime | < 5s on 0 rows (new tables only) | Two new tables, no backfill |

---

## 4. Code Examples (Before / After)

### 4.1 Models (NEW)
```python
# app/models/feature_flag.py
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    flag_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="boolean")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    default_value: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    rollout_percentage: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    targeting_rules: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    variants: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    audit_log: Mapped[list["FeatureFlagAudit"]] = relationship(
        back_populates="flag", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "flag_type IN ('boolean','variant','json')",
            name="ck_feature_flags_type",
        ),
        CheckConstraint(
            "rollout_percentage BETWEEN 0 AND 100",
            name="ck_feature_flags_rollout_range",
        ),
        CheckConstraint(
            "key ~ '^[a-z][a-z0-9_-]{0,126}$'",
            name="ck_feature_flags_key_format",
        ),
    )


class FeatureFlagAudit(Base):
    __tablename__ = "feature_flag_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    flag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("feature_flags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    flag: Mapped[FeatureFlag] = relationship(back_populates="audit_log")
```

### 4.2 Cache layer (NEW)
```python
# app/core/feature_flag_cache.py
import asyncio
import json
import time
from collections import OrderedDict
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings

CACHE_TTL_SECONDS = settings.FEATURE_FLAG_CACHE_TTL
MAX_CACHE_SIZE = 10_000
INVALIDATION_CHANNEL = "feature_flags:invalidate"


class FeatureFlagCache:
    """
    In-process LRU cache with TTL. Invalidated by Redis pubsub.
    Per-worker (each FastAPI worker has its own copy).
    """

    def __init__(self) -> None:
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._invalidation_task: asyncio.Task | None = None

    async def get(self, key: str) -> dict | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: dict) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)
            while len(self._store) > MAX_CACHE_SIZE:
                self._store.popitem(last=False)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def start_invalidation_listener(self, redis: Redis) -> None:
        async def _listen():
            pubsub = redis.pubsub()
            await pubsub.subscribe(INVALIDATION_CHANNEL)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                payload = json.loads(message["data"])
                key = payload.get("key")
                if key == "*":
                    await self.clear()
                elif key:
                    await self.invalidate(key)

        self._invalidation_task = asyncio.create_task(_listen())

    async def stop(self) -> None:
        if self._invalidation_task:
            self._invalidation_task.cancel()


_cache: FeatureFlagCache | None = None


def get_flag_cache() -> FeatureFlagCache:
    global _cache
    if _cache is None:
        _cache = FeatureFlagCache()
    return _cache


async def publish_invalidation(redis: Redis, key: str) -> None:
    await redis.publish(INVALIDATION_CHANNEL, json.dumps({"key": key}))
```

### 4.3 Evaluator (NEW)
```python
# app/core/feature_flag_evaluator.py
import asyncio
import hashlib
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_flag_cache import get_flag_cache
from app.core.config import settings
from app.models.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)

EVAL_TIMEOUT_S = settings.FEATURE_FLAG_EVAL_TIMEOUT_MS / 1000


class FlagContext:
    """User/tenant/environment context passed to flag evaluation."""

    __slots__ = ("user_id", "tenant_id", "environment", "attributes")

    def __init__(
        self,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        environment: str = "production",
        attributes: dict[str, Any] | None = None,
    ):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.environment = environment
        self.attributes = attributes or {}


async def is_enabled(
    session: AsyncSession,
    key: str,
    context: FlagContext,
    default: bool = False,
) -> bool:
    """Boolean flag evaluation. Never raises; returns `default` on any error."""
    try:
        return await asyncio.wait_for(
            _evaluate_boolean(session, key, context, default),
            timeout=EVAL_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("flag.eval_failed key=%s err=%r → default=%s", key, exc, default)
        return default


async def get_variant(
    session: AsyncSession,
    key: str,
    context: FlagContext,
    default: str = "control",
) -> str:
    """Multi-variant flag evaluation. Returns variant name (e.g. 'A', 'B')."""
    try:
        return await asyncio.wait_for(
            _evaluate_variant(session, key, context, default),
            timeout=EVAL_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("flag.variant_failed key=%s err=%r → default=%s", key, exc, default)
        return default


async def _load_flag(session: AsyncSession, key: str) -> dict | None:
    cache = get_flag_cache()
    cached = await cache.get(key)
    if cached is not None:
        return cached

    stmt = select(FeatureFlag).where(FeatureFlag.key == key)
    flag = (await session.execute(stmt)).scalar_one_or_none()
    if flag is None:
        return None

    payload = {
        "id": str(flag.id),
        "key": flag.key,
        "flag_type": flag.flag_type,
        "enabled": flag.enabled,
        "rollout_percentage": flag.rollout_percentage,
        "targeting_rules": flag.targeting_rules,
        "variants": flag.variants,
        "kill_switch": flag.kill_switch,
        "default_value": flag.default_value,
    }
    await cache.set(key, payload)
    return payload


async def _evaluate_boolean(
    session: AsyncSession, key: str, context: FlagContext, default: bool
) -> bool:
    flag = await _load_flag(session, key)
    if flag is None:
        return default
    if flag["kill_switch"]:
        return False
    if not flag["enabled"]:
        return False

    # 1. Targeting rules
    matched = _match_targeting(flag["targeting_rules"], context)
    if matched is not None:
        return bool(matched)

    # 2. Percentage rollout (deterministic by user_id)
    if flag["rollout_percentage"] > 0 and context.user_id is not None:
        bucket = _bucket(context.user_id, key)
        if bucket < flag["rollout_percentage"]:
            return True
    return False


async def _evaluate_variant(
    session: AsyncSession, key: str, context: FlagContext, default: str
) -> str:
    flag = await _load_flag(session, key)
    if flag is None:
        return default
    if flag["kill_switch"] or not flag["enabled"]:
        return default

    matched = _match_targeting(flag["targeting_rules"], context)
    if isinstance(matched, str):
        return matched

    # Variant assignment via consistent hashing
    if not flag["variants"] or context.user_id is None:
        return default
    bucket = _bucket(context.user_id, key)
    cumulative = 0
    for variant in flag["variants"]:
        cumulative += variant["weight"]
        if bucket < cumulative:
            return variant["name"]
    return default


def _match_targeting(rules: list, context: FlagContext) -> Any:
    """Returns matched value, or None if no rule matched."""
    for rule in rules:
        attr = rule["attribute"]
        op = rule["operator"]
        target = rule["value"]
        actual = _resolve_attr(attr, context)
        if _check(op, actual, target):
            return rule.get("return_value", True)
    return None


def _resolve_attr(attr: str, context: FlagContext) -> Any:
    if attr == "user_id":
        return str(context.user_id) if context.user_id else None
    if attr == "tenant_id":
        return str(context.tenant_id) if context.tenant_id else None
    if attr == "environment":
        return context.environment
    return context.attributes.get(attr)


def _check(op: str, actual: Any, target: Any) -> bool:
    if op == "equals":
        return actual == target
    if op == "in":
        return actual in target
    if op == "not_in":
        return actual not in target
    return False


def _bucket(user_id: UUID, flag_key: str) -> int:
    """Deterministic 0..99 bucket via SHA-256 of (user_id || flag_key)."""
    seed = f"{user_id}:{flag_key}".encode()
    digest = hashlib.sha256(seed).digest()
    return digest[0] % 100
```

### 4.4 Decorator + dependency for FastAPI (NEW)
```python
# app/core/feature_flag_deps.py
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.core.feature_flag_evaluator import FlagContext, is_enabled


def require_flag(key: str, default: bool = False):
    """
    FastAPI dependency that 404s the route if the flag is disabled
    for the current user.

    Usage:
        @router.get(
            "/beta/feature",
            dependencies=[Depends(require_flag("new_dashboard"))],
        )
    """

    async def dep(
        current_user: CurrentUser,
        session: SessionDep,
    ) -> None:
        ctx = FlagContext(
            user_id=current_user.id,
            tenant_id=getattr(current_user, "tenant_id", None),
        )
        if not await is_enabled(session, key, ctx, default=default):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Feature not available",
            )

    return dep
```

### 4.5 Routes (NEW, admin-only when `with_admin_ui=True`)
```python
# app/api/routes/feature_flags.py
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentSuperuser, SessionDep
from app.core.feature_flag_cache import publish_invalidation
from app.core.redis import get_redis
from app.crud import feature_flag as crud_flag
from app.schemas.feature_flag import (
    FeatureFlagCreate,
    FeatureFlagPublic,
    FeatureFlagUpdate,
)

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


@router.post("/", response_model=FeatureFlagPublic, status_code=status.HTTP_201_CREATED)
async def create_flag(
    flag_in: FeatureFlagCreate,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> FeatureFlagPublic:
    existing = await crud_flag.get_by_key(session, key=flag_in.key)
    if existing:
        raise HTTPException(status_code=409, detail="Flag key already exists")
    flag = await crud_flag.create(session, flag_in=flag_in, actor_id=current_user.id)
    return FeatureFlagPublic.model_validate(flag)


@router.patch("/{key}", response_model=FeatureFlagPublic)
async def update_flag(
    key: str,
    flag_in: FeatureFlagUpdate,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> FeatureFlagPublic:
    flag = await crud_flag.get_by_key(session, key=key)
    if not flag:
        raise HTTPException(status_code=404)
    flag = await crud_flag.update(session, flag=flag, flag_in=flag_in, actor_id=current_user.id)

    # Invalidate cache across all workers
    redis = await get_redis()
    await publish_invalidation(redis, key)
    return FeatureFlagPublic.model_validate(flag)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flag(
    key: str,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> None:
    flag = await crud_flag.get_by_key(session, key=key)
    if not flag:
        raise HTTPException(status_code=404)
    await crud_flag.delete(session, flag=flag, actor_id=current_user.id)
    redis = await get_redis()
    await publish_invalidation(redis, key)
```

### 4.6 Migration
```python
# alembic/versions/0009_add_feature_flags.py
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(127), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("flag_type", sa.String(16), server_default="boolean", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("default_value", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("targeting_rules", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("variants", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("kill_switch", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("flag_type IN ('boolean','variant','json')", name="ck_feature_flags_type"),
        sa.CheckConstraint("rollout_percentage BETWEEN 0 AND 100", name="ck_feature_flags_rollout_range"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_-]{0,126}$'", name="ck_feature_flags_key_format"),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"], unique=True)

    op.create_table(
        "feature_flag_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("flag_id", sa.Uuid(), sa.ForeignKey("feature_flags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feature_flag_audit_flag_id", "feature_flag_audit", ["flag_id"])


def downgrade() -> None:
    op.drop_index("ix_feature_flag_audit_flag_id", "feature_flag_audit")
    op.drop_table("feature_flag_audit")
    op.drop_index("ix_feature_flags_key", "feature_flags")
    op.drop_table("feature_flags")
```

---

### 4.10 Deterministic rollout bucketer
```python
# app/feature_flags/bucketer.py
"""Deterministic percentage-rollout bucketing used by FlagEvaluator.

Every user must land in the same bucket for the same flag across restarts,
across workers, and across deploys. This module is the single source of
bucketing so the property is verified by one unit test.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketResult:
    bucket: int  # 0..99
    in_rollout: bool


def bucket_for_user(flag_key: str, user_id: str) -> int:
    """Return the user's bucket (0..99) for a flag using SHA-256 mod 100."""
    if not flag_key or not user_id:
        raise ValueError("flag_key and user_id must be non-empty")
    payload = f"{flag_key}|{user_id}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    # Interpret first 4 bytes as big-endian unsigned int, then mod 100
    bucket_int = int.from_bytes(digest[:4], byteorder="big", signed=False)
    return bucket_int % 100


def in_percentage_rollout(flag_key: str, user_id: str, percentage: int) -> BucketResult:
    """Return True iff the user lands below the rollout percentage (0..100)."""
    if not 0 <= percentage <= 100:
        raise ValueError(f"percentage must be in [0, 100], got {percentage}")
    bucket = bucket_for_user(flag_key, user_id)
    return BucketResult(bucket=bucket, in_rollout=bucket < percentage)
```

### 4.11 Redis pubsub invalidation fan-out
```python
# app/feature_flags/invalidation.py
"""Fan-out flag-config invalidations to every worker via Redis pubsub.

When an operator toggles a flag in the admin API the writing worker
publishes to `feature_flags:invalidate` and every subscribed worker
evicts that key from its in-process LRU cache within ~50 ms.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

import redis.asyncio as redis
import structlog

INVALIDATION_CHANNEL = "feature_flags:invalidate"

log = structlog.get_logger(__name__)


async def publish_invalidation(client: redis.Redis, flag_key: str, actor_id: str) -> None:
    """Called by the admin API after every flag mutation."""
    payload = json.dumps({"flag_key": flag_key, "actor_id": actor_id})
    await client.publish(INVALIDATION_CHANNEL, payload)
    log.info("feature_flag.invalidation.published", flag_key=flag_key, actor_id=actor_id)


async def listen_for_invalidations(
    client: redis.Redis,
    on_invalidate: Callable[[str], Awaitable[None]],
) -> None:
    """Background task: subscribe and invoke on_invalidate for each message."""
    pubsub = client.pubsub()
    await pubsub.subscribe(INVALIDATION_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message["data"])
            except json.JSONDecodeError:
                log.warning("feature_flag.invalidation.bad_payload", raw=message.get("data"))
                continue
            flag_key = data.get("flag_key")
            if not flag_key:
                continue
            try:
                await on_invalidate(flag_key)
                log.info("feature_flag.invalidation.applied", flag_key=flag_key)
            except Exception as exc:  # pragma: no cover — defensive
                log.error("feature_flag.invalidation.handler_failed", flag_key=flag_key, error=str(exc))
    finally:
        await pubsub.unsubscribe(INVALIDATION_CHANNEL)
        await pubsub.close()
```



## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Evaluation never raises** | `is_enabled` and `get_variant` wrap evaluation in try/except + asyncio.wait_for; on any error → return `default`. |
| QS-2 | **Hard latency cap** | `EVAL_TIMEOUT_S` enforced via `asyncio.wait_for`. p99 < 1 ms cached; > 5 ms → default returned. |
| QS-3 | **Cache invalidation is fan-out** | Redis pubsub broadcasts invalidations to ALL workers in < 1s. No worker stays stale beyond cache TTL. |
| QS-4 | **Bucketing is deterministic** | SHA-256(`user_id || flag_key`) % 100. Same user always lands in same bucket for the same flag, even after restart. |
| QS-5 | **Kill switch overrides everything** | If `kill_switch=true`, evaluation returns `False`/`default` immediately, even if `enabled=true`. |
| QS-6 | **Flag changes are audited** | Every `create/update/delete` writes a row to `feature_flag_audit` with before/after state and actor. |
| QS-7 | **Flag keys are URL- and code-safe** | DB CheckConstraint `^[a-z][a-z0-9_-]{0,126}$` rejects bad keys at insert. |
| QS-8 | **Default value is always returned for unknown flags** | Missing flag → `default`. Never raises, never logs error (only debug). |
| QS-9 | **Decorator integrates with FastAPI naturally** | `Depends(require_flag("key"))` returns 404 (not 403) to avoid leaking flag existence. |
| QS-10 | **No flag value is exposed to unauthenticated users** | Public listing endpoint NOT generated by default. Read endpoints require superuser unless `with_admin_ui=False`. |
| QS-11 | **Cache is bounded** | LRU eviction when size > 10k; prevents memory leak in long-running workers. |
| QS-12 | **Targeting rules are strictly typed** | JSON schema validated by Pydantic on create/update. Invalid rules → 422. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `FeatureFlag` model exists at `app/models/feature_flag.py` | File exists |
| CC-02 | `FeatureFlagAudit` model exists in same file | File exists |
| CC-03 | `app/core/feature_flag_cache.py` exists with LRU + TTL | File exists |
| CC-04 | `app/core/feature_flag_evaluator.py` exists with `is_enabled`/`get_variant` | File exists |
| CC-05 | `app/core/feature_flag_deps.py` exists with `require_flag` decorator-dep | File exists |
| CC-06 | `app/crud/feature_flag.py` exists with `create/update/delete/get_by_key` | File exists |
| CC-07 | `app/api/routes/feature_flags.py` exists (admin-only) | File exists |
| CC-08 | `app/schemas/feature_flag.py` has `Create/Update/Public` schemas | File exists |
| CC-09 | Migration `0009_add_feature_flags.py` exists | File exists |
| CC-10 | Migration creates both tables + check constraints + index | Inspect upgrade() |
| CC-11 | Flag key CheckConstraint is `^[a-z][a-z0-9_-]{0,126}$` | grep |
| CC-12 | `flag_type` CheckConstraint is `boolean/variant/json` | grep |
| CC-13 | `rollout_percentage` CheckConstraint is 0..100 | grep |
| CC-14 | Cache TTL configurable via `settings.FEATURE_FLAG_CACHE_TTL` | Found in core/config.py |
| CC-15 | Eval timeout configurable via `settings.FEATURE_FLAG_EVAL_TIMEOUT_MS` | Found in core/config.py |
| CC-16 | Pubsub channel constant `INVALIDATION_CHANNEL` exported | grep |
| CC-17 | App startup wires `start_invalidation_listener` | grep in `main.py` lifespan |
| CC-18 | Routes registered in `app/api/main.py` only when `with_admin_ui=True` | Inspect router include |
| CC-19 | OpenAPI exposes new endpoints when admin UI enabled | curl /openapi.json |
| CC-20 | Existing test suite passes | pytest 0 failures |
| CC-21 | New file `tests/test_feature_flags.py` with 30 tests | File exists |
| CC-22 | All files parse with `ast.parse` | Tool internal step |
| CC-23 | Tool execution time < 4s | Time measurement |
| CC-24 | Cache hit ratio > 99% in benchmark | Benchmark T-29 |
| CC-25 | Eval p99 < 1 ms (cached) | Benchmark T-29 |
| CC-26 | Bucketing deterministic across runs | T-12 |
| CC-27 | Kill switch overrides enabled flag | T-08 |
| CC-28 | Update propagates < 1s across workers | T-22 |
| CC-29 | Idempotent re-run | T-26 |
| CC-30 | Audit row written for every flag change | T-09 |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 7 Invariants enforced (see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (see §10)
- [ ] Tool is idempotent: run twice, identical state
- [ ] Tool is reversible: rollback procedure documented and tested
- [ ] Migration safety: tested on empty DB and on existing app
- [ ] Performance budget met: eval p99 < 1 ms, cache hit > 99%
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated (KNOWLEDGE.md, manifest.yaml, SKILL.md)
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-FF-01 | Flag evaluation NEVER raises an exception to the caller | `try/except` wrapper + `asyncio.wait_for` with `default` return on any error | T-04, T-05, T-30 |
| INV-FF-02 | An unknown flag key NEVER fails — it returns the caller's `default` | `_load_flag` returns None → evaluator returns default | T-04 |
| INV-FF-03 | The kill switch ALWAYS overrides `enabled=true` | First check in `_evaluate_boolean` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-08 |
| INV-FF-04 | Bucketing is deterministic for the same `(user_id, flag_key)` pair across processes | SHA-256 hash, no randomness — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-12 |
| INV-FF-05 | Flag updates ALWAYS publish invalidation to all workers | Routes call `publish_invalidation` after every update/delete | T-22 |
| INV-FF-06 | Evaluation latency is bounded by `EVAL_TIMEOUT_S` | `asyncio.wait_for(..., timeout=EVAL_TIMEOUT_S)` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-30 |
| INV-FF-07 | Every flag mutation produces exactly one audit row | CRUD layer writes audit inside the same transaction as the flag mutation | T-09, T-10 |

---

## 9. User Stories

### 9.1 Flag evaluation basics (US-01 .. US-05)

**US-01: Tool scaffolds the full feature-flag subsystem in one call**
- **As a** backend engineer adding experimentation to a live FastAPI service
- **I want** to run `add_feature_flags(project_dir)` and get every required file generated
- **So that** my team can start shipping features dark without writing boilerplate
- **Given:** a FastAPI project with auth (User model) and Redis configured
- **When:** I call `add_feature_flags(project_dir, with_admin_ui=True)`
- **Then:**
  - Files `app/models/feature_flag.py`, `app/core/feature_flag_cache.py`, `app/core/feature_flag_evaluator.py`, `app/core/feature_flag_deps.py`, `app/crud/feature_flag.py`, `app/api/routes/feature_flags.py`, `app/schemas/feature_flag.py`, and the Alembic migration are created (CC-01 through CC-09)
  - The tool returns `{files_created: ≥8, files_modified: ≤4, notes: [...]}` with no errors
  - Running `pytest` against the unmodified existing test suite exits 0 (CC-20)

**US-02: Boolean flag with 100% rollout returns True for any authenticated user**
- **As a** product engineer toggling on a completed feature for all users
- **I want** `is_enabled(session, "new_checkout", FlagContext(user_id=user.id))` to return `True`
- **So that** every user immediately sees the new checkout flow without a redeploy
- **Given:** flag `new_checkout` exists with `enabled=true, rollout_percentage=100, kill_switch=false`
- **When:** any authenticated user's request evaluates the flag
- **Then:**
  - `is_enabled()` returns `True` for every distinct `user_id` tested (T-01)
  - No DB query is made after the first evaluation due to in-process cache (CC-03, CC-14)
  - Evaluation completes in under 1 ms p99 when cache is warm (INV-FF-06)

**US-03: Boolean flag for a disabled feature returns the caller's default without raising**
- **As a** developer defensively wrapping a feature still in development
- **I want** `is_enabled(session, "unreleased_payments", ctx, default=False)` to always return `False`
- **So that** the feature stays hidden even if I forget to configure the flag before deploy
- **Given:** no flag named `unreleased_payments` exists in the database
- **When:** any code path calls `is_enabled(session, "unreleased_payments", ctx, default=False)`
- **Then:**
  - Returns `False` exactly (INV-FF-02)
  - No exception propagates to the caller (INV-FF-01)
  - No ERROR-level log entry is emitted; at most a DEBUG trace (CC-04)
  - Behavior is identical whether `default=False` or `default=True` is passed — caller controls it (T-04)

**US-04: Variant flag assigns the same A/B bucket to the same user across calls**
- **As a** data scientist running a pricing experiment
- **I want** `get_variant(session, "pricing_test", FlagContext(user_id=uid))` to return the same variant every time for the same user
- **So that** a user always sees the same price treatment and experiment data is not contaminated
- **Given:** flag `pricing_test` with `variants=[{name:"control",weight:50},{name:"treatment",weight:50}]` and `enabled=true`
- **When:** I call `get_variant()` for the same `user_id` across multiple requests and worker restarts
- **Then:**
  - The returned variant is always the same string for that user (INV-FF-04)
  - Bucketing uses `SHA-256(flag_key|user_id) % 100` with no random component (CC-26, T-12)
  - Across 1000 distinct users, variant distribution falls between 450 and 550 for each bucket (T-13)

**US-05: `require_flag` dependency returns 404, not 403, when a flag is disabled**
- **As a** backend engineer gating a beta route so it is invisible to ineligible users
- **I want** `Depends(require_flag("beta_dashboard"))` to return 404 when the flag is off
- **So that** the route's existence is not leaked to users who are not in the experiment
- **Given:** route `GET /beta/dashboard` is decorated with `dependencies=[Depends(require_flag("beta_dashboard"))]` and flag `beta_dashboard` is disabled for the current user
- **When:** an ineligible user hits `GET /beta/dashboard`
- **Then:**
  - HTTP response status is `404 Not Found` (not 403) (CC-05, QS-9)
  - Response body contains `"Feature not available"`, not the flag key name
  - An eligible user (flag enabled) receives `200 OK` with normal response body (T-06)

---

### 9.2 Targeting rules (US-06 .. US-10)

**US-06: `user_id` allowlist rule enables a flag only for named beta testers**
- **As a** release manager doing private beta with five specific users
- **I want** to add a targeting rule `{attribute:"user_id", operator:"in", value:["uid-a","uid-b","uid-c"]}` to a flag
- **So that** only those three users see the new feature regardless of rollout percentage
- **Given:** flag `internal_redesign` with `enabled=true, rollout_percentage=0` and the above targeting rule
- **When:** `is_enabled()` is called for `user_id="uid-a"` and for `user_id="uid-z"`
- **Then:**
  - `uid-a` gets `True` even though `rollout_percentage=0` (targeting rules take priority) (T-06)
  - `uid-z` gets `False` (not in allowlist, rollout is 0) (CC-04)
  - The rule is stored as a validated JSON array; Pydantic rejects malformed operators with 422 (CC-12, QS-12)

**US-07: `tenant_id` equality rule gates a flag to a single paying tenant**
- **As a** SaaS operator enabling a premium feature for one enterprise tenant before GA
- **I want** a targeting rule `{attribute:"tenant_id", operator:"equals", value:"tenant-acme"}` on flag `advanced_reports`
- **So that** Acme's users get the feature while all other tenants see the default behaviour
- **Given:** flag `advanced_reports` with `enabled=true, rollout_percentage=0` and the tenant targeting rule
- **When:** user from `tenant-acme` evaluates the flag vs. user from `tenant-other`
- **Then:**
  - `tenant-acme` user receives `True` (T-07)
  - `tenant-other` user receives `False`
  - FlagContext carries `tenant_id` from the request context var without any extra wiring (CC-04)
  - Changing the tenant in the rule and calling PATCH triggers cache invalidation within 1s (INV-FF-05)

**US-08: Kill switch immediately disables a flag regardless of enabled and rollout state**
- **As a** on-call SRE responding to a production incident caused by a flag
- **I want** to `PATCH /feature-flags/broken_checkout {"kill_switch": true}` and have all workers stop serving the feature within seconds
- **So that** I can mitigate user impact without a redeploy
- **Given:** flag `broken_checkout` is `enabled=true, rollout_percentage=100` and is actively returning `True`
- **When:** I PATCH `kill_switch=true` on the flag
- **Then:**
  - All subsequent `is_enabled()` calls return `False` within 1 second (INV-FF-03, CC-27)
  - Cache invalidation is published via Redis pubsub and all workers evict the entry (INV-FF-05, T-20)
  - A `feature_flag_audit` row is written with `before_state.kill_switch=false` and `after_state.kill_switch=true` (INV-FF-07, T-10)

**US-09: Environment attribute rule confines a flag to the staging environment**
- **As a** QA engineer validating a new payment flow before production release
- **I want** a targeting rule `{attribute:"environment", operator:"equals", value:"staging"}` on flag `new_payment_flow`
- **So that** the flag is automatically active in staging and inactive in production without separate flag configs
- **Given:** flag `new_payment_flow` with `enabled=true, rollout_percentage=0` and the environment rule
- **When:** FlagContext is constructed with `environment="staging"` vs `environment="production"`
- **Then:**
  - Staging context returns `True`; production context returns `False` (CC-04)
  - `_resolve_attr("environment", ctx)` returns the correct string without DB lookup (CC-04)
  - No separate flag record is needed per environment (T-06)

**US-10: `not_in` operator denies a flag to a denylist of user IDs**
- **As a** compliance officer needing to suppress a feature for users under legal hold
- **I want** a targeting rule `{attribute:"user_id", operator:"not_in", value:["uid-frozen-1","uid-frozen-2"]}` combined with `rollout_percentage=100`
- **So that** frozen users can never access the feature even when global rollout is 100%
- **Given:** flag `export_feature` with `enabled=true, rollout_percentage=100` and the `not_in` rule listed first
- **When:** `is_enabled()` is called for `uid-frozen-1` vs. a normal user
- **Then:**
  - `uid-frozen-1` receives `False` because the denylist rule fires before percentage evaluation (T-07)
  - Normal users receive `True` from the 100% rollout
  - Pydantic schema validates `operator` is one of `equals/in/not_in` and rejects unknown values with 422 (QS-12)

---

### 9.3 Rollout & kill-switch (US-11 .. US-15)

**US-11: Percentage rollout at 50% produces statistically even split across users**
- **As a** growth engineer running a gradual rollout to 50% of users
- **I want** `rollout_percentage=50` to produce a roughly even split across a large user population
- **So that** I can measure impact on half the user base before going to 100%
- **Given:** flag `new_onboarding` with `enabled=true, rollout_percentage=50, kill_switch=false`
- **When:** I call `is_enabled()` for 1 000 randomly generated UUIDs
- **Then:**
  - Between 450 and 550 users receive `True` (±5% tolerance) (T-13, CC-26)
  - The same user always lands in the same bucket across calls (INV-FF-04)
  - `_bucket(user_id, flag_key)` returns values in `[0, 99]` (T-11)

**US-12: Rollout at 0% means no users see the feature**
- **As a** engineer deploying a dark-launched feature before the rollout decision
- **I want** `rollout_percentage=0` to guarantee zero users are exposed
- **So that** I can merge the feature branch without any accidental exposure
- **Given:** flag `dark_feature` with `enabled=true, rollout_percentage=0` and no targeting rules
- **When:** I evaluate the flag for 1 000 distinct users
- **Then:**
  - Every evaluation returns `False` (T-14)
  - No exception is raised for any user_id (INV-FF-01)
  - Setting `rollout_percentage=1` and re-evaluating produces at most ~10 True results (T-13)

**US-13: Rollout bucket is sticky across restarts and new worker spawns**
- **As a** platform engineer scaling out from 2 to 8 Gunicorn workers during peak traffic
- **I want** a user's bucket assignment to remain identical on new workers
- **So that** a user does not flicker between enabled and disabled as requests round-robin across workers
- **Given:** flag `sticky_checkout` with `rollout_percentage=30` and a specific user `uid-test`
- **When:** `_bucket("sticky_checkout", "uid-test")` is called on any worker or after an app restart
- **Then:**
  - Result is the same integer value every time (INV-FF-04, CC-26)
  - SHA-256 over `"sticky_checkout|uid-test"` encoded as UTF-8, first 4 bytes as big-endian unsigned int mod 100 (T-12)
  - No process state, clock, or random seed affects the result (CC-26)

**US-14: Emergency full-kill disables all flags for all users via global `*` invalidation**
- **As a** SRE during a total service degradation
- **I want** to publish `{"key": "*"}` to the `feature_flags:invalidate` channel to wipe every worker's cache
- **So that** all flags reload from the authoritative DB state on next evaluation
- **Given:** 4 workers all have their LRU caches populated with 500+ flag entries each
- **When:** `publish_invalidation(redis, "*")` is called
- **Then:**
  - All workers' caches are fully cleared within 1 second (CC-16, T-21)
  - The next evaluation per flag hits the DB and re-populates the cache from current DB state
  - Workers that have the invalidation listener running pick up the event without restart (INV-FF-05)

**US-15: Anonymous user with no `user_id` is never included in percentage rollout**
- **As a** product manager ensuring anonymous visitors cannot accidentally enter a paid-user-only experiment
- **I want** `FlagContext(user_id=None)` to be excluded from percentage rollout even at 100%
- **So that** only authenticated users with stable IDs participate in experiments
- **Given:** flag `premium_analytics` with `enabled=true, rollout_percentage=100` and no targeting rules
- **When:** `is_enabled()` is called with `FlagContext(user_id=None)`
- **Then:**
  - Returns `False` (no bucket can be computed) (CC-04, T-21)
  - No exception or warning is emitted (INV-FF-01)
  - A targeting rule can still explicitly grant anonymous users access if desired (EC-4)

---

### 9.4 Admin lifecycle (US-16 .. US-20)

**US-16: Superadmin creates a new flag and audit row is written atomically**
- **As a** platform admin setting up a new A/B test
- **I want** `POST /feature-flags/ {key:"checkout_v2", flag_type:"boolean", rollout_percentage:10}` to create the flag and record its creation in one database transaction
- **So that** the audit trail is never missing a create event even under concurrent writes
- **Given:** superadmin JWT, no existing flag named `checkout_v2`
- **When:** I POST the flag creation payload
- **Then:**
  - Response is `201 Created` with `FeatureFlagPublic` body including the new UUID (CC-07)
  - One `feature_flag_audit` row exists with `action="create"`, `actor_id=<admin_id>`, `before_state=null`, `after_state=<full flag json>` (INV-FF-07, CC-30)
  - A second POST with the same key returns `409 Conflict` (CC-07)

**US-17: PATCH on a flag produces a before/after audit row and triggers cache invalidation**
- **As a** release manager escalating rollout from 10% to 50%
- **I want** `PATCH /feature-flags/checkout_v2 {"rollout_percentage": 50}` to update the flag and record the change
- **So that** I can later reconstruct the exact moment rollout changed when analysing experiment results
- **Given:** flag `checkout_v2` exists with `rollout_percentage=10`
- **When:** superadmin sends the PATCH request
- **Then:**
  - Response is `200 OK` with updated `FeatureFlagPublic` (CC-07)
  - Audit row has `before_state.rollout_percentage=10`, `after_state.rollout_percentage=50`, `actor_id` set (INV-FF-07, T-10)
  - `publish_invalidation(redis, "checkout_v2")` is called; workers' cached entry is evicted within 1s (INV-FF-05, CC-28)

**US-18: Deleting a flag cascades the audit log and publishes invalidation**
- **As a** admin retiring a completed experiment
- **I want** `DELETE /feature-flags/old_experiment` to remove the flag and its audit history together
- **So that** the DB stays clean and no stale cached entry lingers on any worker
- **Given:** flag `old_experiment` with 12 audit rows exists
- **When:** superadmin sends `DELETE /feature-flags/old_experiment`
- **Then:**
  - Response is `204 No Content` (CC-07)
  - `feature_flag_audit` rows for `old_experiment` are deleted via `CASCADE` (CC-02)
  - `publish_invalidation(redis, "old_experiment")` is called; all workers evict the entry (INV-FF-05)

**US-19: Regular user cannot create, update, or delete flags**
- **As a** security reviewer verifying RBAC on the admin endpoints
- **I want** all flag mutation endpoints to reject non-superuser tokens with 403
- **So that** unprivileged API clients cannot manipulate experiment flags
- **Given:** regular user JWT (not superadmin)
- **When:** regular user attempts `POST /feature-flags/`, `PATCH /feature-flags/k`, or `DELETE /feature-flags/k`
- **Then:**
  - All three requests return `403 Forbidden` (CC-07, QS-10, T-27)
  - No `feature_flag_audit` row is written
  - No cache invalidation is published (INV-FF-05 integrity preserved)

**US-20: Tool is idempotent — re-running against an already-instrumented project is a no-op**
- **As a** CI pipeline operator running `add_feature_flags` on every PR
- **I want** repeated runs to detect existing files and skip creation
- **So that** the tool never overwrites hand-edited flag configuration
- **Given:** `add_feature_flags` was previously run and all 8+ files exist
- **When:** I run `add_feature_flags(project_dir)` a second time
- **Then:**
  - No files are overwritten; `files_created=0, files_modified=0` in the return dict (CC-29, T-26)
  - The existing `pytest` suite still exits 0 (CC-20)
  - The Alembic migration is NOT duplicated (CC-09)

---

### 9.5 Observability & edge cases (US-21 .. US-25)

**US-21: Cold-start evaluation hits DB exactly once per flag, then caches**
- **As a** performance engineer benchmarking flag overhead at startup
- **I want** the first evaluation of a flag after a worker restart to hit the DB and then serve all subsequent calls from the in-process LRU cache
- **So that** DB connection count stays flat under steady-state traffic
- **Given:** worker just restarted; LRU cache is empty; flag `checkout_v2` exists in DB
- **When:** `is_enabled(session, "checkout_v2", ctx)` is called 100 times in a tight loop
- **Then:**
  - Exactly one `SELECT` against `feature_flags` is executed (T-16, T-17)
  - Calls 2–100 return in under 1 ms p99 with zero DB round-trips (CC-25)
  - The cache entry carries a monotonic timestamp used for TTL expiry (CC-03, CC-14)

**US-22: LRU cache evicts the least-recently-used entry when the 10 001st flag is cached**
- **As a** infrastructure engineer operating a service with a very large number of flags
- **I want** the in-process cache to never grow beyond 10 000 entries
- **So that** worker memory stays below the 5 MB budget regardless of flag proliferation
- **Given:** LRU cache is at exactly 10 000 entries; entry `oldest_flag` was cached first and not accessed since
- **When:** a new entry `newest_flag` is inserted
- **Then:**
  - `oldest_flag` is evicted from the cache (CC-03, T-19)
  - `newest_flag` is retrievable immediately after insertion
  - Total cache size remains ≤ 10 000 (QS-11)
  - The `asyncio.Lock` prevents concurrent eviction races (EC-12)

**US-23: TTL expiry causes cache miss and DB reload after 60 seconds**
- **As a** ops engineer who updates a flag but does not want to wait for Redis pubsub
- **I want** the in-process TTL to guarantee that every worker re-fetches flag state from DB within 60 seconds at most
- **So that** Redis pubsub is an optimisation, not a hard dependency for consistency
- **Given:** flag `experiment_x` was cached at time `t0`; TTL is configured to 60 seconds
- **When:** `is_enabled()` is called at `t0 + 61` seconds (TTL elapsed)
- **Then:**
  - Cache returns `None`; the evaluator falls back to a DB query (T-18, CC-03, CC-14)
  - The refreshed value is stored in the cache with a new TTL timestamp
  - The total propagation delay without Redis is ≤ `cache_ttl_seconds` as specified (CC-14, CC-15)

**US-24: Redis pubsub outage does not prevent flag evaluation — fallback to DB + TTL**
- **As a** SRE during a Redis connection interruption
- **I want** flag evaluation to continue serving from DB (with TTL-only invalidation) while Redis is down
- **So that** a Redis outage degrades cache freshness but never takes down the feature-flag system
- **Given:** the Redis connection drops after startup; the invalidation listener coroutine dies
- **When:** `is_enabled()` is called for both cached and uncached flags
- **Then:**
  - Cached entries are served normally until TTL expires (T-24, INV-FF-01)
  - On cache miss, DB is queried directly and the result is re-cached (CC-03, CC-04)
  - No exception propagates to the API caller; at most a WARNING is logged (INV-FF-01, QS-1)
  - When Redis reconnects, the invalidation listener resumes without a worker restart (EC-3)

**US-25: Evaluation p99 stays under 1 ms at 10 000 cached evaluations per second**
- **As a** architect sizing compute for a high-traffic service making flag checks on every request
- **I want** the in-process evaluation path to impose negligible overhead even at 10k req/s
- **So that** I can add flag checks freely without a performance budget conversation
- **Given:** flag cache is warm; `FEATURE_FLAG_EVAL_TIMEOUT_MS=5`; single-process asyncio event loop
- **When:** I run a synthetic benchmark of 10 000 consecutive `is_enabled()` calls against the warm cache
- **Then:**
  - p99 latency is below 1 ms (CC-24, CC-25, T-29)
  - No evaluations time out (circuit breaker at 5 ms not triggered) (INV-FF-06, T-30)
  - Memory for the cache stays under 5 MB for 10 000 entries (QS-11)

## 10. Test Plan

### 10.1 Functional tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Boolean flag enabled returns True | flag enabled, 100% rollout | is_enabled() | True |
| T-02 | Boolean flag disabled returns False | flag enabled=false | is_enabled() | False |
| T-03 | Variant flag returns assigned variant | flag with A/B 50/50 | get_variant() | "A" or "B" consistently |
| T-04 | Missing flag returns default | no flag | is_enabled(default=True) | True |
| T-05 | Eval never raises | corrupt JSON in DB | is_enabled() | default returned, no exception |
| T-06 | Targeting allowlist user_id | rule user_id IN [u1] | is_enabled(user_id=u1) | True |
| T-07 | Targeting denylist user_id | rule user_id NOT IN [u1] | is_enabled(user_id=u1) | False |
| T-08 | Kill switch overrides enabled | enabled=true, kill=true | is_enabled() | False |
| T-09 | Create writes audit row | POST /feature-flags/ | inspect audit | row with action=create |
| T-10 | Update writes audit row | PATCH /feature-flags/k | inspect audit | row with before/after |

### 10.2 Bucketing & rollout

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | Bucket is in [0,99] | random user_id+key | _bucket() | 0..99 |
| T-12 | Bucket is deterministic | same (uid,key) called twice | _bucket() | identical |
| T-13 | Rollout 50% gives ~50% True | 1000 random users, 50% rollout | count True | 450..550 |
| T-14 | Rollout 0% gives 0 True | 1000 users, 0% rollout | count True | 0 |
| T-15 | Rollout 100% gives 1000 True | 1000 users, 100% rollout | count True | 1000 |

### 10.3 Cache & invalidation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-16 | Cache miss hits DB | cold cache | is_enabled() | DB queried |
| T-17 | Cache hit doesn't hit DB | warm cache | is_enabled() | DB not queried |
| T-18 | TTL expires after configured seconds | TTL=1s, cached at t0 | check at t0+1.5 | reloaded |
| T-19 | LRU evicts oldest | fill cache > MAX_SIZE | inspect cache | oldest dropped |
| T-20 | Pubsub invalidation clears local entry | 2 workers, A updates | check B | entry gone within 1s |
| T-21 | Global `*` clears entire cache | populated cache | publish * | empty |
| T-22 | Update propagates < 1s across workers | 2 workers, A patches | B's next eval | new value |

### 10.4 Failure modes

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-23 | DB unreachable returns default | DB down | is_enabled(default=False) | False, warning logged |
| T-24 | Redis down → eval still works | redis off | is_enabled() | DB-only path works |
| T-25 | Slow DB > timeout returns default | mock 10ms delay, timeout=5ms | is_enabled() | default returned |

### 10.5 Admin, integration, performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-26 | Tool re-run is no-op | already installed | run tool | no file changes |
| T-27 | Regular user cannot create flag | regular token | POST /feature-flags/ | 403 |
| T-28 | Superadmin can manage flags | superadmin token | CRUD | 201/200/204 |
| T-29 | Eval p99 < 1 ms cached | warm cache, 10k iters | benchmark | p99 < 1 ms |
| T-30 | Eval respects 5ms timeout under stress | sleep 10ms in DB | benchmark | timeout fires, default returned |

---

## 11. Interaction Matrix

How `add_feature_flags` interacts with other tools:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Tenancy first** | ✅ Compatible | Flags can target by `tenant_id` attribute. FlagContext carries tenant_id from contextvar. |
| `add_audit_log` | No | ✅ Compatible | Flag CRUD writes its own audit table; the global audit log is unaffected. |
| `add_rbac` | **RBAC first** | ✅ Compatible | `require_flag` is composable with role checks; both must pass. |
| `add_cache_layer` | No | ✅ Compatible | Flag cache is separate from generic Redis cache; they don't conflict. |
| `add_circuit_breaker` | No | ✅ Compatible | The evaluator already has its own breaker (`asyncio.wait_for`). |
| `add_rate_limit` | No | ✅ Compatible | Flag eval is in-process; doesn't count toward request rate limits. |
| `add_oauth2_provider` | **Auth first** | ✅ Compatible | OAuth user.id used as bucket seed. |
| `add_api_key_auth` | **Auth first** | ⚠️ Caveat | API keys may not have a stable user_id; bucket falls back to API key id. |
| `add_outbox_pattern` | No | ⚠️ Caveat | If a flag rollout triggers an event, the rollout decision must be persisted alongside the event for replay determinism. |
| `add_long_running_task` | No | ⚠️ Caveat | Background tasks should snapshot flag value at task creation, not re-evaluate during execution (otherwise behavior changes mid-task). |
| `add_search` | No | ✅ Compatible | Flag queries do not interfere with search. |
| `add_soft_delete` | No | ✅ Compatible | Flags themselves are not soft-deleted; hard delete with audit. |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

If `add_feature_flags` produces broken state, the rollback procedure is:

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/feature_flag.py app/core/feature_flag_*.py \
  app/crud/feature_flag.py app/api/routes/feature_flags.py app/schemas/feature_flag.py \
  app/main.py app/api/main.py app/core/config.py
rm alembic/versions/*_add_feature_flags.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
This drops both `feature_flags` and `feature_flag_audit` tables.

### Data preservation rollback
If flag definitions must be preserved:
```sql
CREATE TABLE _feature_flags_archive AS SELECT * FROM feature_flags;
CREATE TABLE _feature_flag_audit_archive AS SELECT * FROM feature_flag_audit;
-- Then run alembic downgrade -1
```

### Failure mode: tool partially modified files
The tool MUST be atomic (§15.13). If atomicity fails:
1. Identify modified files via `git status`
2. `git checkout -- {files}` to revert
3. Delete partial migration: `rm alembic/versions/*_add_feature_flags.py`
4. Re-run tool

### Emergency: a flag is causing production issues
1. Use the kill switch: `PATCH /feature-flags/{key} {"kill_switch": true}`
2. Cache invalidation propagates within 1s; all workers return False/default for that flag
3. No redeploy needed

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no Redis | Tool errors: "Feature flags require Redis for cache invalidation. Configure REDIS_URL first." |
| EC-2 | Project has no User model | Tool errors: "Feature flags require an authenticated user model. Add auth first." |
| EC-3 | Migration runs but Redis is down | Migration completes; runtime falls back to DB-only path with TTL-only invalidation |
| EC-4 | A flag with `rollout_percentage=50` and an anonymous user (user_id=None) | Rollout NOT applied (no bucket); only targeting rules considered |
| EC-5 | Two superadmins update the same flag concurrently | Last-write-wins at DB level; audit log captures both writes; cache invalidated twice |
| EC-6 | An update sets variant weights that don't sum to 100 | Pydantic validator rejects with 422 |
| EC-7 | A flag key with uppercase letters | DB CheckConstraint rejects on insert; CRUD raises 422 before reaching DB |
| EC-8 | Pubsub message arrives for a flag the worker has never cached | No-op (cache.invalidate(key) is idempotent) |
| EC-9 | Eval called outside of a request (background job) | Works; pass a synthetic FlagContext |
| EC-10 | Flag table is empty | All evaluations return defaults; the operation returns a structured error response and no side effects persist |
| EC-11 | A targeting rule references an attribute not in context | `_resolve_attr` returns None; rule does NOT match; falls through to next |
| EC-12 | Cache LRU eviction during high concurrency | `asyncio.Lock` ensures atomic eviction; no race conditions |
| EC-13 | A flag is deleted while a request is mid-flight | Cached entry serves until next miss/invalidation; missing flag returns default |
| EC-14 | The pubsub channel name conflicts with another system | Constant is namespaced (`feature_flags:invalidate`); collisions are unlikely |
| EC-15 | Worker restart loses cache | Cold start; first eval per flag hits DB, then warms |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 30 CC verified by automated check
2. ✅ All 25 user stories have passing acceptance tests
3. ✅ All 30 test cases pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified by integration tests
7. ✅ Rollback procedure tested end-to-end
8. ✅ Performance SLOs measured and met
9. ✅ Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10
10. ✅ One human dev uses it on a real project to ship a dark-launch and rolls it from 0% → 100% without incident

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists (auth installed)
- [ ] Validate Redis URL is configured (`settings.REDIS_URL`)
- [ ] Validate Alembic initialized
- [ ] Detect existing `feature_flags` table → idempotent skip if found
- [ ] Detect existing `app/models/feature_flag.py` → idempotent skip
- [ ] Verify idempotency: run the tool twice on the same project and confirm the second run returns `status="already_installed"` without modifying any files

### 15.2 Models
- [ ] Create `app/models/feature_flag.py` with `FeatureFlag` + `FeatureFlagAudit`
- [ ] Add CheckConstraints
- [ ] Verify file parses
- [ ] Confirm `FeatureFlag.rollout_percentage` has a `CheckConstraint("rollout_percentage BETWEEN 0 AND 100")` by inspecting `FeatureFlag.__table_args__` in `tests/test_feature_flag_model.py::test_rollout_check_constraint`
- [ ] Run `ruff check app/models/feature_flag.py` and `mypy app/models/feature_flag.py --strict` with zero findings
- [ ] Add `## [Unreleased]` entry to `CHANGELOG.md` documenting the two new tables `feature_flags` and `feature_flag_audit`

### 15.3 Cache module
- [ ] Create `app/core/feature_flag_cache.py`
- [ ] Implement `FeatureFlagCache` (OrderedDict + asyncio.Lock + TTL + LRU)
- [ ] Implement `start_invalidation_listener` and `publish_invalidation`
- [ ] Verify file parses
- [ ] Confirm LRU eviction: fill cache to `max_size`, insert one more entry, and assert the oldest key is removed in `tests/test_feature_flag_cache.py::test_lru_eviction`
- [ ] Verify `publish_invalidation` triggers immediate eviction from `FeatureFlagCache` within TTL in `tests/test_feature_flag_cache.py::test_pubsub_invalidation_removes_cached_flag`
- [ ] Run `ruff check app/core/feature_flag_cache.py` with zero findings

### 15.4 Evaluator module
- [ ] Create `app/core/feature_flag_evaluator.py`
- [ ] Implement `FlagContext` class
- [ ] Implement `is_enabled` with `asyncio.wait_for` + try/except
- [ ] Implement `get_variant`
- [ ] Implement `_load_flag` (cache → DB → cache fill)
- [ ] Implement `_match_targeting`, `_resolve_attr`, `_check`
- [ ] Implement `_bucket` (SHA-256 deterministic)
- [ ] Verify file parses

### 15.5 Decorator-dependency module
- [ ] Create `app/core/feature_flag_deps.py`
- [ ] Implement `require_flag(key, default)`
- [ ] Returns 404, not 403
- [ ] Verify file parses
- [ ] Confirm `require_flag("disabled_feature")` returns HTTP 404 (not 403 or 500) when the flag is disabled in `tests/test_feature_flags.py::test_require_flag_returns_404_when_disabled`
- [ ] Confirm `require_flag("missing_flag", default=True)` allows the request through when the flag does not exist in the DB in `tests/test_feature_flags.py::test_require_flag_default_true_passes`
- [ ] Run `ruff check app/core/feature_flag_deps.py` and `mypy app/core/feature_flag_deps.py --strict` with zero findings

### 15.6 CRUD
- [ ] Create `app/crud/feature_flag.py` with `create/update/delete/get_by_key/list`
- [ ] Each mutation writes audit row in same transaction
- [ ] Verify file parses
- [ ] Confirm every mutation (`create`, `update`, `delete`) writes a corresponding `FeatureFlagAudit` row in the same DB transaction by querying `feature_flag_audit` after each call in `tests/test_feature_flags.py::test_crud_mutations_write_audit_rows`
- [ ] Run `ruff check app/crud/feature_flag.py` and `mypy app/crud/feature_flag.py --strict` with zero findings
- [ ] Add `## [Unreleased]` entry to `CHANGELOG.md` documenting CRUD endpoints for feature flags at `/feature-flags/`

### 15.7 Schemas
- [ ] Create `app/schemas/feature_flag.py` with `FeatureFlagCreate/Update/Public`
- [ ] Pydantic validators on `key`, `rollout_percentage`, `variants` (sum to 100), `targeting_rules`
- [ ] Verify file parses
- [ ] Verify `FeatureFlagCreate` validator rejects `variants` weights that do not sum to 100 with a `ValidationError` in `tests/test_feature_flag_schemas.py::test_variants_must_sum_to_100`
- [ ] Run `ruff check app/schemas/feature_flag.py` and `mypy app/schemas/feature_flag.py --strict` with zero findings
- [ ] Confirm `FeatureFlagPublic` does not expose internal `targeting_rules` raw JSON without going through the schema (field is included but typed correctly)

### 15.8 Routes (when `with_admin_ui=True`)
- [ ] Create `app/api/routes/feature_flags.py`
- [ ] POST/GET/PATCH/DELETE — all require `CurrentSuperuser`
- [ ] On every mutation, call `publish_invalidation(redis, key)`
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Confirm `PATCH /feature-flags/{key}` calls `publish_invalidation(redis, key)` by asserting the Redis pubsub channel receives the message within 100 ms in `tests/test_feature_flags.py::test_patch_publishes_invalidation`
- [ ] Run `tests/test_feature_flags.py::test_non_superuser_cannot_patch_flag` and confirm HTTP 403 is returned for regular users

### 15.9 Settings
- [ ] Add `FEATURE_FLAG_CACHE_TTL: int = 60` to `settings`
- [ ] Add `FEATURE_FLAG_EVAL_TIMEOUT_MS: int = 5` to `settings`
- [ ] Verify `.env.example` contains both `FEATURE_FLAG_CACHE_TTL` and `FEATURE_FLAG_EVAL_TIMEOUT_MS` by running `grep -c "FEATURE_FLAG_CACHE_TTL\|FEATURE_FLAG_EVAL_TIMEOUT_MS" .env.example` and asserting count == 2
- [ ] Run `ruff check app/core/config.py` and `mypy app/core/config.py --strict` with zero new findings after settings additions
- [ ] Confirm `FEATURE_FLAG_CACHE_TTL` is passed to `FeatureFlagCache.__init__` at app startup (not hardcoded) by grepping `app/main.py` for `settings.FEATURE_FLAG_CACHE_TTL`
- [ ] Add `## [Unreleased]` CHANGELOG entry noting the two new settings with their defaults
- [ ] Add structured log event `feature_flag.eval` with fields `key`, `result`, `duration_ms` emitted by `is_enabled` in `app/core/feature_flag_evaluator.py`

### 15.10 App startup wiring
- [ ] Modify `app/main.py` lifespan to call `get_flag_cache().start_invalidation_listener(redis)` on startup
- [ ] Call `await cache.stop()` on shutdown
- [ ] Confirm startup calls `start_invalidation_listener` exactly once by spying on it in `tests/test_feature_flags.py::test_lifespan_starts_listener`
- [ ] Confirm graceful shutdown calls `cache.stop()` in the lifespan teardown section of `app/main.py`
- [ ] Run `ruff check app/main.py` with zero new findings after the lifespan modification
- [ ] Confirm `CHANGELOG.md` lifespan section mentions the invalidation listener startup
- [ ] Add OpenTelemetry trace span `feature_flag.cache.invalidation_received` with attribute `flag_key` in `start_invalidation_listener` callback

### 15.11 Migration
- [ ] Generate `0NNN_add_feature_flags.py`
- [ ] `upgrade()` creates both tables + index + constraints
- [ ] `downgrade()` drops in reverse
- [ ] Verify migration parses
- [ ] Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a clean Postgres container and assert each step exits with code 0
- [ ] Verify both `feature_flags` and `feature_flag_audit` tables exist after `alembic upgrade head` via `psql -c "\dt feature_flag*"` outputting 2 rows
- [ ] Run `ruff check alembic/versions/0NNN_add_feature_flags.py` with zero findings

### 15.12 Test generation
- [ ] Create `tests/test_feature_flags.py` with all 30 tests
- [ ] Use existing fixtures + new `superadmin_token`, `mock_redis` fixtures
- [ ] Verify file parses
- [ ] Run `pytest tests/test_feature_flags.py -v` and confirm all 30 test cases pass including SHA-256 bucketing determinism test
- [ ] Verify SHA-256 bucketing is deterministic by running `tests/test_feature_flags.py::test_same_user_same_bucket` 1000 times via `pytest --count=1000` (or loop in the test) and asserting 0 flips
- [ ] Run `ruff check tests/test_feature_flags.py` with zero findings
- [ ] Confirm `CHANGELOG.md` test section documents the 30 new tests and the `superadmin_token` fixture

### 15.13 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback ALL writes
- [ ] Drop partially-created tables on failure
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Inject a failure after writing `app/models/feature_flag.py` but before `app/core/feature_flag_cache.py` and assert `app/models/feature_flag.py` is not present on disk after rollback in `tests/test_tool_atomicity.py::test_feature_flag_rollback_on_cache_write`
- [ ] Run `ruff check app/core/feature_flag_evaluator.py app/core/feature_flag_deps.py` with zero findings post-rollback
- [ ] Verify the `files_rolled_back` list in the error dict matches the set of files written before the injected failure

### 15.14 Documentation
- [ ] Append feature-flags section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Confirm `manifest.yaml` contains `fastapi_add_feature_flags` entry: `python -c "import yaml; d=yaml.safe_load(open('manifest.yaml')); assert any(t['name']=='fastapi_add_feature_flags' for t in d['tools'])"`
- [ ] Verify `core/KNOWLEDGE.md` feature-flags section documents the SHA-256 bucketing algorithm, `require_flag` dependency, and the Redis pubsub invalidation channel name
- [ ] Run `ruff check app/api/routes/feature_flags.py` and `mypy app/api/routes/feature_flags.py --strict` with zero findings

### 15.15 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer (benchmark unchanged)
- [ ] Measure tool execution time
- [ ] Measure eval p99 latency
- [ ] Run `pytest tests/ --ignore=tests/test_feature_flags.py -q` and confirm zero regressions on previously-green tests

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/feature_flag.py",
    "app/core/feature_flag_cache.py",
    "app/core/feature_flag_evaluator.py",
    "app/core/feature_flag_deps.py",
    "app/crud/feature_flag.py",
    "app/schemas/feature_flag.py",
    "app/api/routes/feature_flags.py",
    "alembic/versions/0009_add_feature_flags.py",
    "tests/test_feature_flags.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/core/config.py",
    "app/api/main.py"
  ],
  "metrics": {
    "execution_time_ms": 3214,
    "files_changed": 12,
    "lines_added": 891,
    "lines_removed": 4,
    "cache_ttl_seconds": 60,
    "eval_timeout_ms": 5
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_feature_flags.py -v",
    "Create your first flag: POST /feature-flags/ {key: 'new_dashboard', flag_type: 'boolean'}",
    "Use it in code: `if await is_enabled(session, 'new_dashboard', FlagContext(user_id=user.id)): ...`",
    "Use it on a route: `@router.get('/beta', dependencies=[Depends(require_flag('new_dashboard'))])`"
  ],
  "warnings": [
    "Admin UI endpoints are exposed at /feature-flags. Restrict via reverse proxy in production if you do not want them publicly reachable.",
    "Cache invalidation requires Redis pubsub. If Redis is unavailable, workers will be stale up to FEATURE_FLAG_CACHE_TTL seconds (60s default)."
  ],
  "notes": [
    "Feature flags installed with cache_ttl=60s, eval_timeout=5ms.",
    "Two new tables: feature_flags, feature_flag_audit.",
    "Lifespan hook installed in main.py to start the invalidation listener.",
    "Existing tests still pass: 51/51."
  ]
}
```
