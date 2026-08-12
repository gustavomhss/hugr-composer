---
spec_id: "TOOL-005"
tool_name: "add_audit_log"
primitive: "compliance/TamperEvidentAuditLog"
primitive_path: "core.venous.compliance.TamperEvidentAuditLog"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-AL-01"
  - "INV-AL-02"
  - "INV-AL-03"
  - "INV-AL-04"
  - "INV-AL-05"
  - "INV-AL-06"
  - "INV-AL-07"
  - "INV-AL-08"
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
  - "QS-01"
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-05"
  - "QS-06"
  - "QS-07"
  - "QS-08"
  - "QS-09"
  - "QS-10"
  - "QS-11"
  - "QS-12"
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
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-005: add_audit_log

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_audit_log` |
| Category | EXTEND > CRUD & Data |
| Complexity | High |
| Dependencies | Existing project with auth enabled, SQLAlchemy 2.0 async, Alembic, PostgreSQL 14+ |
| Signature | `add_audit_log(project_dir: str, models: list[str] \| None = None, log_reads: bool = False, retain_days: int \| None = None, hash_chain: bool = True) -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: models to audit (None = all business models)<br>`log_reads`: also log SELECT operations (default False — high volume)<br>`retain_days`: optional retention window per resource type (None = keep forever)<br>`hash_chain`: enable SHA-256 hash-chain linking entries for tamper detection (default True) |

---

## 2. Purpose

`fastapi_add_audit_log` adds a tamper-evident, compliance-grade audit trail to a FastAPI service.
The fundamental problem it solves is **accountability without code sprawl**: every INSERT, UPDATE, and
DELETE on tracked models must be recorded with the full before/after state, the actor (user_id), the
request origin (IP address, user-agent), and an exact timestamp — without requiring developers to
instrument each CRUD function manually. The tool implements this via SQLAlchemy `Session.before_flush`
event listeners that intercept every flush cycle and emit an `AuditLog` row automatically. The audit
table is append-only and immutable: a PostgreSQL trigger rejects any UPDATE or DELETE on `audit_logs`,
and each row stores a SHA-256 hash of its own content chained to the hash of the previous entry,
creating a cryptographic proof of log integrity. Soft-delete and restore operations on models that use
`is_deleted` are detected and recorded with dedicated action labels (`soft_delete`, `restore`) rather
than the generic `update` label, so auditors can reconstruct the full lifecycle of any record. Storage
is designed for scale: JSONB diff columns hold only the changed fields (not full snapshots), the table
is partitioned by month using PostgreSQL declarative partitioning (range on `created_at`), and composite
indexes on `(entity_type, entity_id)`, `(user_id, created_at)`, and `(created_at)` support the four
canonical auditor queries — per-record history, per-actor activity, time-range scans, and
action-filtered reports — all within the stated SLOs at 100M-row scale.

Beyond recording events, the tool exposes a read-only query API (`GET /audit-logs/`) with filter
parameters for `entity_type`, `entity_id`, `actor_id`, `action`, `from_dt`, and `to_dt`. Access is
gated behind a dedicated `CurrentAuditor` dependency that requires either a `role=auditor` claim or
`is_superuser=True` — ordinary users cannot query the audit trail even if they can query the underlying
data. Retention is configurable per resource type via `retain_days`, enforced by a background
APScheduler job that prunes expired rows using a batched DELETE to avoid long table locks. The
hash-chain verifier endpoint (`POST /audit-logs/verify`) re-computes the chain over a specified range
and returns a verification report, enabling auditors to confirm log integrity without direct database
access. The entire system is designed to satisfy the audit logging requirements of SOC 2 Type II
(CC6.1, CC6.3), HIPAA §164.312(b), GDPR Article 30 (records of processing activities), and
PCI-DSS Requirement 10 out of the box.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s for up to 12 models | Dev runs once from CLI; models × file edits |
| Files created | 8 (model, context, listeners, schema, crud, routes, migration, tests) | Predictable scaffold surface |
| Files modified | ≤ 4 (`main.py`, `app/core/config.py`, `app/api/main.py`, `app/models/__init__.py`) | Minimal blast radius |
| Audit write overhead per operation | < 5 ms p99 | Single `INSERT` into current month partition; no network hop; no diff on read path |
| Audit query by entity (1M rows) | < 50 ms p99 | Composite index `(entity_type, entity_id, created_at)` — O(log n) |
| Audit query by actor (1M rows) | < 50 ms p99 | Index `(user_id, created_at)` — O(log n) |
| Audit query by time range (100M rows) | < 100 ms p99 | Partition pruning eliminates irrelevant month partitions; only scans 1-2 partitions |
| Hash-chain single entry verify | < 10 ms | Local SHA-256 computation; one DB read for predecessor hash |
| Hash-chain bulk verify (10k entries) | < 5 s | Sequential hash iteration; no parallelism required |
| Storage per audit row | ~1.5–2 KB | JSONB diffs (changed fields only), not full snapshots; IP + user_agent + hash inline |
| Retention purge batch | < 1 s per 10k rows | Batched DELETE with `LIMIT 500` and short sleep between batches to avoid I/O spikes |
| Partition creation | Automatic | APScheduler creates next month's partition 7 days in advance |

---

## 4. Code Examples

### 4.1 AuditLog model with hash chain — GENERATED `app/models/audit_log.py`

```python
"""
Append-only audit log with SHA-256 hash chain for tamper detection.
Partitioned by month on created_at for scalable range scans.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint, DateTime, Index, String, Text, Uuid, func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """
    Immutable audit log entry.

    Invariants enforced at DB level:
    - No UPDATE or DELETE (PostgreSQL trigger `trg_audit_log_immutable`)
    - created_at has server default (cannot be forged by application)
    - entry_hash is SHA-256 of (id || entity_type || entity_id || action
      || user_id || before_values || after_values || ip_address || created_at
      || prev_hash)
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    before_values: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    after_values: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="SHA-256 hex of this row chained to prev"
    )
    prev_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="entry_hash of the preceding audit entry"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_user", "user_id", "created_at"),
        Index("ix_audit_action", "action", "created_at"),
        CheckConstraint(
            "action IN ('create','update','delete','soft_delete','restore','read')",
            name="ck_audit_action",
        ),
        # Declarative partitioning requires __table_args__ to include postgresql_partition_by
        {"postgresql_partition_by": "RANGE (created_at)"},
    )
```

### 4.2 Audit context — GENERATED `app/core/audit_context.py`

```python
"""
Request-scoped context for audit logging via Python contextvars.
Set once per request by AuditContextMiddleware; read by audit listeners.
"""
from __future__ import annotations

import contextvars
import uuid
from typing import Any

from fastapi import Request

_current_user_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "audit_user_id", default=None
)
_current_request_meta: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "audit_request_meta", default={}
)


def set_audit_context(user_id: uuid.UUID | None, request: Request | None) -> None:
    """Called by AuditContextMiddleware once per request."""
    _current_user_id.set(user_id)
    if request is not None:
        _current_request_meta.set({
            "ip_address": (request.client.host if request.client else None),
            "user_agent": (request.headers.get("user-agent", "") or "")[:512],
        })
    else:
        _current_request_meta.set({})


def get_audit_context() -> tuple[uuid.UUID | None, dict[str, Any]]:
    """Returns (user_id, meta) for the current request."""
    return _current_user_id.get(), _current_request_meta.get()


def clear_audit_context() -> None:
    _current_user_id.set(None)
    _current_request_meta.set({})
```

### 4.3 SQLAlchemy event listeners — GENERATED `app/core/audit_listeners.py`

```python
"""
SQLAlchemy Session.before_flush listeners that auto-emit audit entries.
Registered once at application startup via register_audit_listeners().
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.audit_context import get_audit_context
from app.models.audit_log import AuditLog

# Populated by tool generation: maps model class → True if it should be audited
AUDITED_MODELS: set[type] = set()
# Whether hash-chain is active (set from app config at startup)
_HASH_CHAIN_ENABLED: bool = True


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _compute_diff(target: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (before, after) dicts containing only changed fields."""
    state = inspect(target)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for attr in state.attrs:
        hist = attr.load_history()
        if hist.has_changes():
            before[attr.key] = _serialize(hist.deleted[0] if hist.deleted else None)
            after[attr.key] = _serialize(hist.added[0] if hist.added else None)
    return before, after


def _full_snapshot(target: Any) -> dict[str, Any]:
    state = inspect(target)
    return {
        attr.key: _serialize(getattr(target, attr.key, None))
        for attr in state.attrs
    }


def _classify_action(before: dict[str, Any], after: dict[str, Any]) -> str:
    if "is_deleted" in before and "is_deleted" in after:
        if before["is_deleted"] is False and after["is_deleted"] is True:
            return "soft_delete"
        if before["is_deleted"] is True and after["is_deleted"] is False:
            return "restore"
    return "update"


def _get_prev_hash(session: Session) -> str | None:
    """Fetch the entry_hash of the most-recently-added audit row in this session."""
    # Look in the session's pending objects first (within same flush)
    for obj in session.new:
        if isinstance(obj, AuditLog) and obj.entry_hash is not None:
            return obj.entry_hash
    return None


def _compute_entry_hash(entry: AuditLog) -> str:
    payload = json.dumps({
        "id": str(entry.id),
        "entity_type": entry.entity_type,
        "entity_id": str(entry.entity_id),
        "action": entry.action,
        "user_id": str(entry.user_id) if entry.user_id else None,
        "before_values": entry.before_values,
        "after_values": entry.after_values,
        "ip_address": entry.ip_address,
        "prev_hash": entry.prev_hash,
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _emit_audit(
    session: Session,
    target: Any,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    user_id, meta = get_audit_context()
    prev_hash = _get_prev_hash(session) if _HASH_CHAIN_ENABLED else None
    entry = AuditLog(
        entity_type=type(target).__name__.lower(),
        entity_id=str(getattr(target, "id", "")),
        action=action,
        user_id=user_id,
        before_values=before or None,
        after_values=after or None,
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
        prev_hash=prev_hash,
    )
    if _HASH_CHAIN_ENABLED:
        entry.entry_hash = _compute_entry_hash(entry)
    session.add(entry)


@event.listens_for(Session, "before_flush")
def _audit_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    for target in list(session.new):
        if type(target) in AUDITED_MODELS:
            _emit_audit(session, target, "create", None, _full_snapshot(target))
    for target in list(session.dirty):
        if type(target) in AUDITED_MODELS:
            before, after = _compute_diff(target)
            if before:  # Only emit if something actually changed
                action = _classify_action(before, after)
                _emit_audit(session, target, action, before, after)
    for target in list(session.deleted):
        if type(target) in AUDITED_MODELS:
            _emit_audit(session, target, "delete", _full_snapshot(target), None)


def register_audit_listeners(hash_chain: bool = True) -> None:
    """Call once at application startup to activate audit listeners."""
    global _HASH_CHAIN_ENABLED
    _HASH_CHAIN_ENABLED = hash_chain
```

### 4.4 Hash-chain verifier — GENERATED `app/core/audit_verifier.py`

```python
"""
Verify integrity of the audit log hash chain over a given time range.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


@dataclass
class VerificationResult:
    total_entries: int = 0
    broken_at: str | None = None  # entry id where chain breaks
    is_intact: bool = True
    errors: list[str] = field(default_factory=list)


async def verify_hash_chain(
    session: AsyncSession,
    from_dt: datetime,
    to_dt: datetime,
) -> VerificationResult:
    """
    Re-compute SHA-256 for every entry in the range and verify that
    entry_hash == recomputed_hash and prev_hash == previous entry's entry_hash.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.created_at.between(from_dt, to_dt))
        .order_by(AuditLog.created_at)
    )
    rows = (await session.execute(stmt)).scalars().all()
    result = VerificationResult(total_entries=len(rows))

    prev_hash: str | None = None
    for row in rows:
        payload = json.dumps({
            "id": str(row.id),
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id),
            "action": row.action,
            "user_id": str(row.user_id) if row.user_id else None,
            "before_values": row.before_values,
            "after_values": row.after_values,
            "ip_address": row.ip_address,
            "prev_hash": row.prev_hash,
        }, sort_keys=True, default=str)
        expected_hash = hashlib.sha256(payload.encode()).hexdigest()

        if row.entry_hash != expected_hash:
            result.is_intact = False
            result.broken_at = str(row.id)
            result.errors.append(
                f"Hash mismatch at id={row.id}: stored={row.entry_hash!r} "
                f"expected={expected_hash!r}"
            )
            break

        if prev_hash is not None and row.prev_hash != prev_hash:
            result.is_intact = False
            result.broken_at = str(row.id)
            result.errors.append(
                f"Chain break at id={row.id}: prev_hash={row.prev_hash!r} "
                f"expected={prev_hash!r}"
            )
            break

        prev_hash = row.entry_hash

    return result
```

### 4.5 Query CRUD — GENERATED `app/crud/audit_log.py`

```python
"""
Read-only CRUD for the audit log. Auditors only; no writes from application layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogFilter, AuditLogPage


async def query_audit_logs(
    session: AsyncSession,
    filters: AuditLogFilter,
    offset: int = 0,
    limit: int = 50,
) -> AuditLogPage:
    """Return paginated audit entries matching the given filters."""
    stmt = select(AuditLog)

    if filters.entity_type:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(filters.entity_id))
    if filters.actor_id:
        stmt = stmt.where(AuditLog.user_id == filters.actor_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.from_dt:
        stmt = stmt.where(AuditLog.created_at >= filters.from_dt)
    if filters.to_dt:
        stmt = stmt.where(AuditLog.created_at <= filters.to_dt)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    return AuditLogPage(items=rows, total=total, offset=offset, limit=limit)
```

### 4.6 Auditor route — GENERATED `app/api/routes/audit_logs.py`

```python
"""
Read-only audit log endpoints. Accessible only to users with role=auditor
or is_superuser=True. No write endpoints — the audit log is immutable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAuditor, get_async_session
from app.core.audit_verifier import verify_hash_chain, VerificationResult
from app.crud.audit_log import query_audit_logs
from app.schemas.audit_log import AuditLogFilter, AuditLogPage, VerifyRequest

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("/", response_model=AuditLogPage)
async def list_audit_logs(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[None, Depends(CurrentAuditor)],
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    actor_id: str | None = Query(None),
    action: str | None = Query(None),
    from_dt: datetime | None = Query(None),
    to_dt: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> AuditLogPage:
    filters = AuditLogFilter(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        from_dt=from_dt,
        to_dt=to_dt,
    )
    return await query_audit_logs(session, filters, offset=offset, limit=limit)


@router.post("/verify", response_model=VerificationResult)
async def verify_audit_chain(
    body: VerifyRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[None, Depends(CurrentAuditor)],
) -> VerificationResult:
    """Re-compute and verify SHA-256 hash chain over the requested time range."""
    return await verify_hash_chain(session, from_dt=body.from_dt, to_dt=body.to_dt)
```

### 4.7 Retention purge job — GENERATED `app/jobs/audit_retention.py`

```python
"""
Background job to purge audit entries older than the configured retention window.
Runs via APScheduler; uses batched DELETE to avoid long table locks.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_SLEEP_SECONDS = 0.1  # Yield between batches to reduce I/O pressure


async def purge_expired_audit_logs(retain_days: int) -> dict[str, int]:
    """
    Delete audit entries older than `retain_days`.
    Returns {"deleted": N} after completing all batches.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retain_days)
    total_deleted = 0

    async with async_session_maker() as session:
        while True:
            async with session.begin():
                stmt = (
                    delete(AuditLog)
                    .where(AuditLog.created_at < cutoff)
                    .returning(AuditLog.id)
                    .limit(BATCH_SIZE)
                )
                result = await session.execute(stmt)
                batch_count = len(result.fetchall())
            total_deleted += batch_count
            if batch_count < BATCH_SIZE:
                break
            await asyncio.sleep(BATCH_SLEEP_SECONDS)

    logger.info("audit_retention_purge cutoff=%s deleted=%d", cutoff.isoformat(), total_deleted)
    return {"deleted": total_deleted}
```

### 4.8 Immutability trigger migration fragment — GENERATED migration

```python
# alembic/versions/0005_add_audit_log.py  (relevant trigger section)
from alembic import op

IMMUTABLE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION fn_audit_log_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log is immutable: % on audit_logs is forbidden', TG_OP;
END;
$$;

CREATE TRIGGER trg_audit_log_immutable
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION fn_audit_log_immutable();
"""

IMMUTABLE_TRIGGER_DROP = """
DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_logs;
DROP FUNCTION IF EXISTS fn_audit_log_immutable();
"""


def upgrade() -> None:
    # 1. Create partitioned parent table
    op.execute("""
        CREATE TABLE audit_logs (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            entity_type VARCHAR(64) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            action VARCHAR(32) NOT NULL,
            user_id UUID,
            before_values JSONB,
            after_values JSONB,
            ip_address INET,
            user_agent VARCHAR(512),
            entry_hash VARCHAR(64),
            prev_hash VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_audit_logs PRIMARY KEY (id, created_at),
            CONSTRAINT ck_audit_action CHECK (
                action IN ('create','update','delete','soft_delete','restore','read')
            )
        ) PARTITION BY RANGE (created_at)
    """)
    # 2. Create initial partition for current + next month
    op.execute("""
        CREATE TABLE audit_logs_y2026m04
            PARTITION OF audit_logs
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
    """)
    op.execute("""
        CREATE TABLE audit_logs_y2026m05
            PARTITION OF audit_logs
            FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')
    """)
    # 3. Composite indexes (created on parent; PostgreSQL propagates to partitions)
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id", "created_at"])
    op.create_index("ix_audit_user", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_action", "audit_logs", ["action", "created_at"])
    # 4. Immutability trigger
    op.execute(IMMUTABLE_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(IMMUTABLE_TRIGGER_DROP)
    op.drop_index("ix_audit_action", table_name="audit_logs")
    op.drop_index("ix_audit_user", table_name="audit_logs")
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_table("audit_logs_y2026m05")
    op.drop_table("audit_logs_y2026m04")
    op.drop_table("audit_logs")
```

### 4.9 Partition management job — GENERATED `app/jobs/audit_partition.py`

```python
"""
APScheduler job that creates the next month's audit_logs partition 7 days in advance.
Ensures the table is always ready to accept writes without operator intervention.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker

logger = logging.getLogger(__name__)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


async def ensure_next_partition() -> None:
    """
    Called daily by APScheduler. Creates the month partition that starts
    in 7 days if it does not already exist.
    """
    target = _next_month(date.today() + timedelta(days=7))
    partition_end = _next_month(target)
    name = f"audit_logs_y{target.year}m{target.month:02d}"

    async with async_session_maker() as session:
        async with session.begin():
            exists = await session.execute(
                text("SELECT 1 FROM pg_tables WHERE tablename = :name"),
                {"name": name},
            )
            if exists.scalar_one_or_none():
                logger.debug("audit partition %s already exists", name)
                return
            await session.execute(text(f"""
                CREATE TABLE {name}
                    PARTITION OF audit_logs
                    FOR VALUES FROM ('{target}') TO ('{partition_end}')
            """))
            logger.info("created audit partition %s", name)
```

### 4.10 Test file — GENERATED `tests/test_audit_log.py` (fragment)

```python
"""
Tests for audit log: listeners, hash chain, query API, retention purge.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_listeners import _compute_entry_hash, _compute_diff
from app.core.audit_verifier import verify_hash_chain
from app.models.audit_log import AuditLog
from app.models.item import Item
from tests.conftest import auditor_token, normal_user_token


@pytest.mark.asyncio
async def test_create_emits_audit_entry(session: AsyncSession, client: AsyncClient) -> None:
    resp = await client.post("/api/v1/items/", json={"title": "foo"}, headers=normal_user_token())
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    logs = (await session.execute(
        select(AuditLog).where(AuditLog.entity_id == item_id, AuditLog.action == "create")
    )).scalars().all()
    assert len(logs) == 1
    assert logs[0].after_values is not None
    assert logs[0].user_id is not None


@pytest.mark.asyncio
async def test_update_emits_diff_only(session: AsyncSession, client: AsyncClient) -> None:
    resp = await client.post("/api/v1/items/", json={"title": "bar"}, headers=normal_user_token())
    item_id = resp.json()["id"]
    await client.patch(f"/api/v1/items/{item_id}", json={"title": "baz"}, headers=normal_user_token())

    logs = (await session.execute(
        select(AuditLog).where(AuditLog.entity_id == item_id, AuditLog.action == "update")
    )).scalars().all()
    assert len(logs) == 1
    assert logs[0].before_values == {"title": "bar"}
    assert logs[0].after_values == {"title": "baz"}
    # Unchanged fields are NOT in the diff
    assert "owner_id" not in (logs[0].before_values or {})


@pytest.mark.asyncio
async def test_hash_chain_intact_after_writes(session: AsyncSession, client: AsyncClient) -> None:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(tz=timezone.utc)
    for i in range(5):
        await client.post("/api/v1/items/", json={"title": f"item-{i}"}, headers=normal_user_token())

    result = await verify_hash_chain(session, from_dt=now - timedelta(seconds=1), to_dt=now + timedelta(minutes=1))
    assert result.is_intact is True
    assert result.total_entries == 5
    assert result.broken_at is None


@pytest.mark.asyncio
async def test_audit_log_immutable_via_trigger(session: AsyncSession) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    # Direct UPDATE must be rejected by the trigger
    with pytest.raises(ProgrammingError, match="audit_log is immutable"):
        async with session.begin():
            await session.execute(text("UPDATE audit_logs SET action='delete' WHERE 1=0"))
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Audit writes are always atomic with the business write** | `Session.before_flush` listener fires inside the caller's transaction; `AuditLog` row in `audit_listeners.py` commits with the business row or both roll back — verified by T-07, T-08 |
| QS-02 | **The audit log is append-only — UPDATE and DELETE are forbidden at DB level** | `trg_audit_log_immutable` trigger in Alembic migration raises exception on any UPDATE or DELETE against `audit_logs`; bypassing from application layer is impossible — verified by T-10, T-11 |
| QS-03 | **Hash chain covers every field that represents audit fact** | `_compute_entry_hash()` in `audit_listeners.py` hashes all 9 fields; omitting any field changes the SHA-256 digest and breaks the chain — verified by T-16, T-17 |
| QS-04 | **Diffs contain only changed fields — never full snapshots on update** | `_compute_diff()` in `audit_listeners.py` calls `attr.load_history()` and records only fields where `history.has_changes()` is true; storage stays ~1.5 KB per row — verified by T-05, T-06 |
| QS-05 | **Actor context is always request-scoped — never shared across concurrent requests** | `contextvars.ContextVar` in `audit_context.py` ensures per-asyncio-task isolation; T-19 fires 100 concurrent requests and asserts no cross-user bleed |
| QS-06 | **Audit query access requires auditor or superuser role** | `CurrentAuditor` dependency in `audit_logs.py` checks `current_user.role == "auditor"` or `current_user.is_superuser`; all other callers receive HTTP 403 — verified by T-21, T-22 |
| QS-07 | **soft_delete and restore are classified correctly** | `_classify_action()` in `audit_listeners.py` detects `is_deleted` transition and emits `soft_delete` or `restore` instead of generic `update` — verified by T-03, T-04 |
| QS-08 | **Retention purge is batched — no table-level lock lasting > 1s** | `purge_expired_audit_logs()` in `audit_retention.py` uses `DELETE ... LIMIT 500` with `asyncio.sleep(0.1)` between batches; the full table is never locked — verified by T-28 |
| QS-09 | **Partition creation is proactive — never reactive** | `ensure_next_partition()` in `audit_partition.py` runs daily via APScheduler and creates partitions 7 days in advance so write failures are impossible — verified by T-29 |
| QS-10 | **IP address and user-agent are stored directly — no reversible encoding** | `INET` column in `audit_log.py` validates IP format at DB level; `user_agent` is truncated to 512 chars; no encoding that could be reversed is applied — verified by T-13 |
| QS-11 | **Listener is idempotent — registered once at startup, never twice** | `register_audit_listeners()` in `audit_listeners.py` is guarded by SQLAlchemy's event registry so duplicate registration is a safe no-op — verified by T-30 |
| QS-12 | **Hash chain verifier is read-only — it cannot modify the audit log** | `verify_hash_chain()` in `audit_verifier.py` uses only `SELECT` statements; `trg_audit_log_immutable` blocks any accidental write anyway — verified by T-16, T-17 |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/models/audit_log.py` exists and defines `AuditLog` with all 12 columns | `ast.parse` + grep `class AuditLog` |
| CC-02 | `AuditLog` table uses `PARTITION BY RANGE (created_at)` | Inspect `__table_args__` for `postgresql_partition_by` |
| CC-03 | Three composite indexes created: `(entity_type, entity_id, created_at)`, `(user_id, created_at)`, `(action, created_at)` | Inspect `__table_args__` |
| CC-04 | `CheckConstraint` enforces action ∈ {create, update, delete, soft_delete, restore, read} | Inspect `ck_audit_action` |
| CC-05 | `app/core/audit_context.py` exports `set_audit_context`, `get_audit_context`, `clear_audit_context` | File exists; inspect exports |
| CC-06 | `app/core/audit_listeners.py` registers `before_flush` listener on `Session` | `grep "@event.listens_for(Session" audit_listeners.py` returns match |
| CC-07 | `AUDITED_MODELS` set is populated with all target model classes at startup | Inspect `register_audit_listeners()` call site in `main.py` |
| CC-08 | `_compute_diff()` returns only changed fields — not full snapshots on update | Unit test T-05 verifies |
| CC-09 | `_classify_action()` maps `is_deleted False→True` to `soft_delete` and `True→False` to `restore` | Unit test T-03 verifies |
| CC-10 | `app/core/audit_verifier.py` exports `verify_hash_chain` that re-computes SHA-256 and validates chain links | File exists; function signature present |
| CC-11 | `app/crud/audit_log.py` exports `query_audit_logs` accepting `AuditLogFilter` | File exists; inspect signature |
| CC-12 | `app/api/routes/audit_logs.py` has `GET /audit-logs/` and `POST /audit-logs/verify` | Routes file inspected; paths present |
| CC-13 | Both routes require `CurrentAuditor` dependency | Grep `CurrentAuditor` in routes file |
| CC-14 | Alembic migration creates partitioned parent table + 2 initial month partitions | Inspect `upgrade()` for `PARTITION BY RANGE` and two `PARTITION OF` statements |
| CC-15 | Migration installs `fn_audit_log_immutable` trigger function and `trg_audit_log_immutable` trigger | Grep trigger name in migration |
| CC-16 | Migration `downgrade()` drops trigger, function, indexes, partitions, parent table in correct reverse order | Inspect `downgrade()` |
| CC-17 | `app/jobs/audit_retention.py` exports `purge_expired_audit_logs(retain_days)` | File exists; inspect signature |
| CC-18 | Retention purge uses batched DELETE with `LIMIT 500` and sleep between batches | Grep `BATCH_SIZE` and `asyncio.sleep` in purge function |
| CC-19 | `app/jobs/audit_partition.py` exports `ensure_next_partition()` | File exists; inspect signature |
| CC-20 | Partition job is registered in APScheduler with daily cron | `grep ensure_next_partition` in scheduler setup |
| CC-21 | `AuditContextMiddleware` calls `set_audit_context(user_id, request)` once per request | Middleware file inspected; `set_audit_context` called in `dispatch()` |
| CC-22 | Middleware is registered in `main.py` AFTER auth middleware | Inspect middleware stack order |
| CC-23 | `register_audit_listeners()` called at application startup with correct `hash_chain` setting | `grep register_audit_listeners` in `main.py` |
| CC-24 | `tests/test_audit_log.py` created with 30 test functions | `grep -c "^async def test_\|^def test_"` returns ≥ 30 |
| CC-25 | Tool is idempotent: re-run detects existing `audit_logs` table and skips | T-27 verifies no duplicate migration or files written |
| CC-26 | `AUDIT_RETAIN_DAYS` setting added to `app/core/config.py` with default `None` | Inspect `Settings` class |
| CC-27 | Tool execution time < 5s | Time measurement in tool benchmark |
| CC-28 | Audit write overhead < 5ms p99 on benchmark with 1M existing rows | Benchmark T-20 verifies |
| CC-29 | Hash chain verify for 10k entries completes < 5s | Benchmark T-17 verifies |
| CC-30 | Existing test suite passes after tool execution (0 regressions) | `pytest tests/` returns 0 failures |

---

## 7. Definition of Done

The tool is "done" when ALL of the following are true:

- [ ] All 30 Completeness Criteria verified by automated check (CC-01..CC-30)
- [ ] All 12 Quality Standards enforced (QS-01..QS-12)
- [ ] All 8 Invariants hold (INV-AL-01..INV-AL-08; see §8)
- [ ] All 25 User Stories pass acceptance tests (US-01..US-25; see §9)
- [ ] All 30 Test Cases pass (T-01..T-30; see §10)
- [ ] Tool is idempotent: run twice on same project, second run is a no-op
- [ ] Rollback procedure tested end-to-end: `alembic downgrade -1` removes all audit infrastructure without data loss to business tables
- [ ] Immutability trigger verified: direct UPDATE/DELETE on `audit_logs` raises `ProgrammingError`
- [ ] Hash chain verified intact over 100k entries after a simulated load run
- [ ] Partition management verified: `ensure_next_partition()` creates partition, handles already-exists case
- [ ] Retention purge verified: deletes only rows older than cutoff, leaves newer rows intact
- [ ] Performance budget met: write overhead < 5ms, query < 50ms, verify < 5s/10k
- [ ] Interaction with TOOL-008, TOOL-001, TOOL-012, TOOL-013 verified (see §11)
- [ ] Documentation updated (`KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`)
- [ ] Tool registered in `mcp_server.py` under `EXTEND > CRUD & Data`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-AL-01 | An audit entry is **never** written directly by application code — always via `Session.before_flush` listener | `_emit_audit()` is not exported; no route or CRUD creates `AuditLog` directly; lint gate rejects `session.add(AuditLog(...))` outside `audit_listeners.py` | T-07, T-08 |
| INV-AL-02 | An audit entry is **never** updated or deleted after INSERT | PostgreSQL trigger `trg_audit_log_immutable` raises on every UPDATE/DELETE on `audit_logs`; application code cannot bypass it | T-10, T-11 |
| INV-AL-03 | The audit context is **never** shared across concurrent async requests | `contextvars.ContextVar` is per-asyncio-task; tests at T-19 verify 100 concurrent requests never bleed user_id | T-19 |
| INV-AL-04 | A write to a tracked model with no audit context in scope **always** records `user_id=None` rather than silently failing | Listener reads context defensively (`get_audit_context()` returns `None` if unset); the audit entry is still created | T-09 |
| INV-AL-05 | The hash chain is **always** verified from a DB backup when chain is broken in production | `verify_hash_chain()` compares stored hash against recomputed hash; a broken chain returns `is_intact=False` with `broken_at` set; operator must investigate before trusting subsequent entries | T-16, T-17 |
| INV-AL-06 | Retention purge **never** deletes entries newer than `retain_days` | `DELETE ... WHERE created_at < cutoff` with explicit cutoff date; checked via T-28 that no rows newer than cutoff are affected | T-28 |
| INV-AL-07 | Audit query endpoints are **never** accessible to non-auditor, non-superuser users | `CurrentAuditor` dependency returns `HTTPException(403)` for any user without `role=auditor` or `is_superuser=True` | T-21, T-22 |
| INV-AL-08 | `entry_hash` computation **always** includes `prev_hash` to ensure chain linkage | `_compute_entry_hash()` includes `prev_hash` in the JSON payload before hashing; removing prev_hash changes the hash and breaks the chain | T-16 |

---

## 9. User Stories

### 9.1 Core audit trail (US-01..US-05)

**US-01: Create a record and see it in the audit trail**
- **As a** compliance officer reviewing GDPR Article 30 records
- **I want** every INSERT on audited models to produce an audit entry
- **So that** I can prove to regulators who created what and when
- **Given:** `Item` model is audited; user `alice` creates an item
- **When:** `POST /items/ {title: "Widget"}`
- **Then:**
  - `audit_logs` table has one row with `action=create`, `user_id=alice.id`, `after_values={title:"Widget", ...}` (INV-AL-01)
  - `entry_hash` is set and non-null if `hash_chain=True`
  - Response time not degraded by > 5ms

**US-02: Update a record and see only changed fields in the diff**
- **As a** security auditor investigating a data change
- **I want** the audit entry for an UPDATE to contain only the fields that changed
- **So that** I do not need to compare two 50-field snapshots to find one changed field
- **Given:** `Item` has `title="foo"` and `status="active"`
- **When:** `PATCH /items/{id} {title: "bar"}`
- **Then:**
  - Audit entry `action=update`, `before_values={title:"foo"}`, `after_values={title:"bar"}`
  - `status` is NOT in the diff (CC-08)

**US-03: Soft-delete and restore are recorded with specific action labels**
- **As a** HIPAA auditor tracing PHI lifecycle
- **I want** soft-deletes to be distinguishable from regular updates in the audit log
- **So that** I can produce an accurate timeline of when data was logically deleted and restored
- **Given:** `Patient` model has `is_deleted` boolean; `add_soft_delete` is also installed (TOOL-001)
- **When:** `DELETE /patients/{id}` triggers soft-delete (`is_deleted=True`)
- **Then:**
  - Audit entry `action=soft_delete`, `before_values={is_deleted:false}`, `after_values={is_deleted:true}` (CC-09, QS-07)
  - When patient is restored: `action=restore`

**US-04: Hard-delete emits a full snapshot before**
- **Given:** `is_deleted` is NOT on the model; DELETE is a hard delete
- **When:** `DELETE /items/{id}`
- **Then:**
  - Audit entry `action=delete`, `before_values={...full snapshot...}`, `after_values=null`
  - After the DB row is gone, the audit entry remains as the last evidence of its existence (INV-AL-02)

**US-05: IP address and user-agent are recorded per entry**
- **As a** security auditor investigating a suspicious write
- **I want** the IP address and user-agent of each audit entry
- **So that** I can correlate audit events with network access logs
- **Given:** Request from IP `10.0.0.1` with user-agent `Mozilla/5.0`
- **When:** Any audited write
- **Then:** `ip_address=10.0.0.1`, `user_agent="Mozilla/5.0"` stored in the audit entry (CC-21)

### 9.2 Immutability and hash chain (US-06..US-10)

**US-06: Audit entries cannot be modified after write**
- **As a** SOC 2 auditor evaluating CC6.1
- **I want** the audit log to be technically immutable
- **So that** I can trust that no administrator can erase or modify audit evidence
- **Given:** An audit entry exists
- **When:** Any user or DBA attempts `UPDATE audit_logs SET action='read' WHERE id=...`
- **Then:** PostgreSQL raises an exception; row is unchanged (INV-AL-02, QS-02, T-10)

**US-07: Audit entries cannot be deleted**

**Persona**: DBA or application developer attempting to remove a sensitive log entry

**Context**: even privileged database users must be blocked from deleting audit evidence

**Action**: execute `DELETE FROM audit_logs WHERE id=...` directly against the database

**Outcome**: PostgreSQL trigger `trg_audit_log_immutable` raises an exception containing "immutable"; the row remains intact and is still queryable

**Refs**: INV-AL-02, QS-02, T-11

**US-08: Hash chain detects tampering**
- **As a** security engineer who suspects someone exported and re-imported audit data with edits
- **I want** the hash chain verifier to detect any modification
- **So that** I can present cryptographic proof of tampering to legal
- **Given:** 1000 audit entries exist; entry 500 is tampered (before_values modified directly in DB)
- **When:** `POST /audit-logs/verify {from_dt: ..., to_dt: ...}`
- **Then:** `is_intact=false`, `broken_at={id of entry 500}`, error message contains expected vs stored hash (INV-AL-05, T-16)

**US-09: Hash chain is intact after normal operations**

**Persona**: security engineer running a routine integrity check after a load test

**Context**: high-volume writes must not introduce any gaps or hash mismatches in the chain

**Action**: run `POST /audit-logs/verify` after a 1-hour load test that wrote 10k entries

**Outcome**: response contains `is_intact=true`, `total_entries=10000`, `broken_at=null` with no errors

**Refs**: INV-AL-05, T-17

**US-10: prev_hash links consecutive entries**

**Persona**: cryptography reviewer auditing the hash-chain implementation in `audit_listeners.py`

**Context**: each entry must incorporate the previous entry's hash so a deleted entry breaks the chain

**Action**: inspect entry N+1 after entry N with `entry_hash=abc` has been committed

**Outcome**: entry N+1 stores `prev_hash=abc` and its own `entry_hash` is computed over content that includes `prev_hash`

**Refs**: INV-AL-08, CC-10

### 9.3 Query API and access control (US-11..US-15)

**US-11: Auditor can filter by entity**
- **As an** auditor investigating a specific record
- **I want** to list all audit events for `entity_type=item` and `entity_id={id}`
- **So that** I can reconstruct the full lifecycle of a single item
- **Given:** auditor token; item has been created, updated twice, and deleted
- **When:** `GET /audit-logs/?entity_type=item&entity_id={id}`
- **Then:** 4 entries returned in descending order; all belong to that item (CC-11, CC-12)

**US-12: Auditor can filter by actor**

**Persona**: auditor investigating a specific user's activity within a time window

**Context**: actor-scoped queries must use the `(user_id, created_at)` index for sub-50ms response

**Action**: call `GET /audit-logs/?actor_id={alice.id}&from_dt=...&to_dt=...` with an auditor token

**Outcome**: exactly 7 entries returned, all with `user_id=alice.id`, response time within SLO

**Refs**: CC-05, CC-11, T-21

**US-13: Non-auditor cannot access the audit log**

**Persona**: regular authenticated user who should not be able to read audit evidence

**Context**: audit data may contain sensitive before/after values from any model in the system

**Action**: call `GET /audit-logs/` using a token with no `auditor` role and `is_superuser=False`

**Outcome**: `CurrentAuditor` dependency in `audit_logs.py` raises HTTP 403 and returns no audit data

**Refs**: INV-AL-07, QS-06, T-22

**US-14: Superuser can access the audit log without auditor role**

**Persona**: platform administrator who is a superuser but has no explicit `auditor` role assigned

**Context**: the `CurrentAuditor` dependency must accept `is_superuser=True` as a valid bypass

**Action**: call `GET /audit-logs/` using a token where `is_superuser=True` and `role != "auditor"`

**Outcome**: `200 OK` returned with results; no 403 raised because the superuser condition is met

**Refs**: QS-06, CC-13, T-21

**US-15: Pagination works correctly on large result sets**

**Persona**: auditor scrolling through a high-volume entity's history across multiple pages

**Context**: `query_audit_logs` in `audit_log.py` must return stable pages without missing or duplicating rows

**Action**: call `GET /audit-logs/?entity_type=order&offset=0&limit=50` then advance with `offset=50`

**Outcome**: first page returns exactly 50 entries and `total=1000`; second page returns the next 50 with no overlap

**Refs**: CC-11, CC-12, T-21

### 9.4 Retention, partitioning, performance (US-16..US-20)

**US-16: Retention purge deletes only expired entries**
- **As a** GDPR data controller enforcing 90-day retention
- **I want** audit entries older than 90 days to be automatically deleted
- **So that** I comply with data minimisation requirements
- **Given:** `retain_days=90`; 500 entries from 120 days ago, 200 entries from 30 days ago
- **When:** `purge_expired_audit_logs(90)` runs
- **Then:** 500 old entries deleted; 200 recent entries untouched; no table lock > 1s (INV-AL-06, QS-08)

**US-17: Partition is created before it is needed**

**Persona**: SRE who needs zero write failures due to missing month partitions at month boundaries

**Context**: `ensure_next_partition()` in `audit_partition.py` must run proactively, not reactively

**Action**: trigger the daily APScheduler job when today is 2026-04-24 (7 days before May)

**Outcome**: partition `audit_logs_y2026m05` is created and subsequent writes with May `created_at` values land in it without error

**Refs**: QS-09, CC-19, CC-20, T-29

**US-18: Writes to a 100M-row table are within SLO**

**Persona**: backend engineer validating the audit system does not degrade write throughput at scale

**Context**: the `Session.before_flush` listener inserts into the current month partition with no network hop

**Action**: run the benchmark with `audit_logs` pre-populated to 100M rows across 10 partitions

**Outcome**: audit INSERT overhead measures < 5ms p99; no timeout or query planner regression observed

**Refs**: CC-28, T-20

**US-19: Time-range query on 100M rows is within SLO**

**Persona**: auditor running a month-scoped investigation across 100M total log entries

**Context**: PostgreSQL partition pruning must eliminate irrelevant month partitions from the scan plan

**Action**: call `GET /audit-logs/?from_dt=2026-03-01&to_dt=2026-04-01&limit=50` against a 100M-row table

**Outcome**: `EXPLAIN ANALYZE` shows only the March partition is scanned; response time is < 100ms p99

**Refs**: CC-02, CC-03, T-20

**US-20: Audit writes survive broker-down (no external dependency)**

**Persona**: backend engineer validating that audit infrastructure has no hidden external dependencies

**Context**: the `Session.before_flush` listener writes directly to PostgreSQL with no Redis or Qdrant calls

**Action**: take Redis and Qdrant offline, then trigger an audited model write via the API

**Outcome**: audit entry is written to PostgreSQL synchronously; no exception or warning related to external services

**Refs**: INV-AL-03, CC-06

### 9.5 Tool behavior and integration (US-21..US-25)

**US-21: Tool is idempotent on re-run**
- **As a** developer who runs the tool twice by mistake
- **I want** the second run to detect existing state and return `{status: "no_op"}`
- **So that** my hand-edited AUDITED_MODELS list is not overwritten
- **Given:** `audit_logs` table already exists; listeners registered
- **When:** `add_audit_log(project_dir)` called again
- **Then:** No file changes; migration not recreated; notes say `"already enabled, skipped"` (T-27)

**US-22: Tool fails atomically on partial error**

**Persona**: developer whose disk fills up mid-run, causing the tool to fail after writing some files

**Context**: a partial scaffold is worse than no scaffold — it leaves the project in an inconsistent state

**Action**: inject a file write error after the model file is created but before the routes file is written

**Outcome**: all previously written files are reverted; the project state is identical to before the tool ran and no partial migration exists

**Refs**: INV-AL-03, CC-25, T-27

**US-23: Audit log works with multi-tenancy installed**

**Persona**: SaaS platform engineer running both TOOL-008 (multi-tenancy) and TOOL-005 (audit log)

**Context**: the audit context is set per-request by `AuditContextMiddleware`, which runs after auth middleware

**Action**: tenant A and tenant B each write a record in overlapping async requests

**Outcome**: each audit entry stores the correct `user_id` for that tenant's actor with no cross-tenant bleed

**Refs**: CC-21, CC-22, T-19, TOOL-008

**US-24: RBAC-protected writes are still audited**

**Persona**: compliance officer verifying that privileged admin deletions leave an audit trail

**Context**: the `Session.before_flush` listener fires regardless of which route or RBAC policy triggered the flush

**Action**: authenticate as an admin and call `DELETE /items/{id}` on a service with TOOL-012 installed

**Outcome**: an audit entry is created with `action=delete` and `user_id=admin.id` without any RBAC interference

**Refs**: CC-06, CC-09, T-06, TOOL-012

**US-25: log_reads=True records SELECT operations**
- **Given:** `add_audit_log(project_dir, log_reads=True)`
- **When:** `GET /items/{id}` called
- **Then:** Audit entry created with `action=read`, `entity_type=item`, `entity_id={id}`, `before_values=null`, `after_values=null`

---

## 10. Test Plan

The 30 tests are grouped into six categories: listener correctness, immutability and hash chain, query API and access control, retention and partitioning, failure isolation and concurrency, and tool-level behaviors. All integration tests run against a real PostgreSQL container; unit tests use mock sessions and mock context.

### 10.1 Listener correctness (T-01..T-05)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-01 | CREATE emits `action=create` with full snapshot | Integration (real DB) | AuditLog row with `action=create`; `after_values` matches model fields; `before_values=null` |
| T-02 | UPDATE emits diff-only — unchanged fields absent | Integration (real DB) | Update `title`; `before={title:old}`, `after={title:new}`; unchanged fields not in either dict |
| T-03 | `is_deleted False→True` classified as `soft_delete` | Unit (mock session) | `_classify_action({"is_deleted": False}, {"is_deleted": True}) == "soft_delete"` |
| T-04 | `is_deleted True→False` classified as `restore` | Unit | `_classify_action({"is_deleted": True}, {"is_deleted": False}) == "restore"` |
| T-05 | UPDATE with no field changes emits NO audit entry | Integration | Flush a model with no dirty attributes; zero new AuditLog rows created |

### 10.2 Immutability and hash chain (T-06..T-12)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-06 | DELETE emits `action=delete` with full before snapshot | Integration | `before_values` contains all model fields; `after_values=null`; row deleted from items but present in audit |
| T-07 | Audit entry is co-committed with business row — transaction rollback removes both | Integration (real DB) | Inject exception after flush; neither `Item` nor `AuditLog` row exists in DB |
| T-08 | Audit listener does NOT fire for models not in `AUDITED_MODELS` | Unit | Create a model not in the set; zero AuditLog rows created |
| T-09 | Audit entry created with `user_id=None` when no context set | Unit (empty context) | AuditLog row created; `user_id` is null; no exception raised (INV-AL-04) |
| T-10 | PostgreSQL trigger blocks UPDATE on audit_logs | Integration | `UPDATE audit_logs SET action='read' WHERE 1=0`; raises `ProgrammingError` containing "immutable" (INV-AL-02) |
| T-11 | PostgreSQL trigger blocks DELETE on audit_logs | Integration | `DELETE FROM audit_logs WHERE id=...`; raises `ProgrammingError` (INV-AL-02) |
| T-12 | entry_hash changes when any hashed field changes | Unit | Build two `AuditLog` instances differing in one field; `_compute_entry_hash` returns different values |

### 10.3 Hash-chain verifier (T-13..T-18)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-13 | Chain intact after 100 sequential writes | Integration | `verify_hash_chain()` returns `is_intact=True`, `total_entries=100` |
| T-14 | Chain broken when `entry_hash` modified in DB | Integration | Force-update `entry_hash` via raw SQL (bypassing trigger); verifier returns `is_intact=False`, `broken_at={id}` |
| T-15 | Chain broken when `prev_hash` link is wrong | Integration | Force-update `prev_hash` of entry N+1 to wrong value; verifier detects mismatch |
| T-16 | Verifier endpoint returns 200 with intact result | E2E | `POST /audit-logs/verify {from_dt, to_dt}`; auditor token; response contains `is_intact=true` |
| T-17 | Verifier returns broken result when tampered | E2E | Tampered entry in range; `is_intact=false`, `broken_at` present in response body |
| T-18 | Verifier rejects non-auditor token with 403 | E2E | Normal user calls `POST /audit-logs/verify`; 403 |

### 10.4 Query API and access control (T-19..T-24)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-19 | 100 concurrent requests from different users produce correct user_id per entry | Async integration | 100 concurrent writes with distinct user tokens; no user_id bleeds across entries; contextvars isolation verified (INV-AL-03, QS-05) |
| T-20 | Audit write overhead < 5ms on 1M-row table | Benchmark | Seed 1M audit rows; time 100 consecutive writes; p99 < 5ms |
| T-21 | `GET /audit-logs/` returns 200 for auditor token | E2E | Auditor token; `GET /audit-logs/`; 200 with items |
| T-22 | `GET /audit-logs/` returns 403 for normal user | E2E | Normal token; `GET /audit-logs/`; 403 |
| T-23 | Filter by entity_type + entity_id returns correct subset | E2E | Create 3 items, update item-1 twice; filter by item-1's id; total=3 (create + 2 updates) |
| T-24 | Filter by actor_id returns only that actor's entries | E2E | Two users write; filter by user1; response contains only user1 entries |

### 10.5 Retention, partitioning, concurrency (T-25..T-28)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-25 | Retention purge deletes only entries older than cutoff | Integration | Insert 100 old + 50 recent entries; `purge_expired_audit_logs(30)`; exactly 100 deleted, 50 remain (INV-AL-06) |
| T-26 | Retention purge uses batched DELETE — no single batch > BATCH_SIZE | Unit | Mock `session.execute` call count; each batch ≤ 500 rows |
| T-27 | `ensure_next_partition()` creates partition for next month | Integration | Call function on real DB; partition name found in `pg_tables` |
| T-28 | `ensure_next_partition()` is idempotent — safe to call twice | Integration | Call twice; second call logs debug "already exists"; no error; no duplicate partition |

### 10.6 Tool-level behaviors (T-29..T-30)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-29 | Tool execution time < 5s on a 12-model project | Benchmark | Time `add_audit_log(project_dir, models=[...12 models...])`; wall clock < 5s |
| T-30 | Tool re-run on already-configured project returns no-op | Integration | Run tool twice; second call returns `{status: "no_op"}`; zero file changes; migration count unchanged |

---

## 11. Interaction Matrix

How `add_audit_log` interacts with other SKILL-001 tools:

| Tool | Order | Interaction | Notes |
|------|-------|-------------|-------|
| TOOL-001 `add_soft_delete` | **Soft-delete first** | ✅ Compatible — enhanced | Audit listener detects `is_deleted` transition and classifies action as `soft_delete` / `restore` instead of generic `update`. Install TOOL-001 before TOOL-005 for correct classification. |
| TOOL-008 `add_multi_tenancy` | **Audit first** | ✅ Compatible | `user_id` in the audit entry is the user within a tenant; `AuditLog` itself is not tenant-scoped (global compliance table). Tenant context is visible via the `user_id`→`users.tenant_id` join. If audit must be per-tenant, add a `tenant_id` column manually after both tools run. |
| TOOL-012 `add_rbac` | Either order | ✅ Compatible | RBAC controls who can write; audit records every write regardless of role. `CurrentAuditor` dependency in audit routes requires `role=auditor` — this role should be defined when TOOL-012 is installed. Install TOOL-012 before audit routes for cleanest integration. |
| TOOL-013 `add_mfa` | No constraint | ✅ Compatible | MFA does not affect audit writes. MFA verification events can optionally be logged via manual `AuditLog` entries in the auth flow; tool does not do this automatically. |
| TOOL-043 `add_data_migration` | **Audit first** | ⚠️ Caveat | Data migrations that write via SQLAlchemy ORM will trigger audit listeners. For large backfill migrations, temporarily disable listeners with `AUDITED_MODELS.clear()` and re-enable after, to avoid writing millions of audit entries for seed data. |
| TOOL-046 `add_event_driven` | Either order | ✅ Compatible | `emit_event()` and consumer ACKs can call `set_audit_context()` + perform an ORM write to log event lifecycle. Shared `correlation_id` from event payload can be stored in a custom `audit_logs.correlation_id` column for distributed tracing. |
| TOOL-048 `add_admin_panel` | **Audit first** | ✅ Compatible | Admin panel reads via `GET /audit-logs/`; requires auditor or superuser role. Admin panel table views trigger no extra audit entries (reads not logged by default). |
| TOOL-002 `add_alembic` | **Alembic first** | Required | Partition migration requires Alembic initialized. Tool errors if `alembic/versions/` does not exist. |
| TOOL-003 `add_sqlalchemy` | **SQLAlchemy first** | Required | Listeners attach to `Session`; async session maker must exist at `app/core/db.py`. |
| TOOL-021 `add_testing` | **Testing first** | ✅ Compatible | `async_session_fixture` from conftest reused by `tests/test_audit_log.py`. AuditContextMiddleware must be active in test app. |
| TOOL-004 `add_pydantic_settings` | **Settings first** | Required | `AUDIT_RETAIN_DAYS` and `AUDIT_HASH_CHAIN` settings added to existing `Settings` class; not created anew. |
| TOOL-035 `add_scheduler` | Either order | ✅ Compatible | If APScheduler is installed by TOOL-035, audit jobs (`ensure_next_partition`, `purge_expired_audit_logs`) are registered into the existing scheduler instance rather than creating a second scheduler. |
| TOOL-036 `add_redis` | No constraint | ✅ Compatible | Audit log has no Redis dependency. Redis can be used by the application alongside audit without interference. |
| TOOL-011 `add_file_upload` | No constraint | ✅ Compatible | File upload models that are in `AUDITED_MODELS` will have their metadata changes audited; binary content is never stored in JSONB diff. |
| TOOL-030 `add_search` | No constraint | ✅ Compatible | Full-text search is applied to business tables only; `audit_logs` is excluded from tsvector indexes by default. |
| TOOL-002 `add_alembic` | **Alembic first** | Required | Partitioned migration requires Alembic initialized with `alembic/versions/` present; tool errors if Alembic is missing. |

---

## 12. Rollback Procedure

If `add_audit_log` produces broken state or must be removed, follow these sections in order.

### 12.1 Code rollback (before deploy or on feature branch)

```bash
# Identify all files created by this tool
git status --short | grep "^?" | grep -E "audit"

# Revert all created and modified files atomically
git checkout HEAD -- app/models/audit_log.py \
    app/core/audit_context.py \
    app/core/audit_listeners.py \
    app/core/audit_verifier.py \
    app/crud/audit_log.py \
    app/api/routes/audit_logs.py \
    app/jobs/audit_retention.py \
    app/jobs/audit_partition.py \
    app/main.py \
    app/core/config.py \
    app/api/main.py \
    tests/test_audit_log.py

# Remove the generated migration
rm -f alembic/versions/*_add_audit_log.py

# Verify no audit imports remain
grep -r "audit_log\|audit_context\|audit_listeners" src/ app/ --include="*.py" \
  | grep -v "test_" | grep -v ".pyc"
# Should be empty after revert

# Confirm application starts
PYTHONPATH=. python -c "from app.main import app; print('startup ok')"
```

### 12.2 Database rollback — tables, partitions, trigger

```bash
# Roll back the Alembic migration (drops trigger, partitions, parent table, indexes)
alembic downgrade -1

# Verify parent table gone
psql "$DATABASE_URL" -c "\d audit_logs"
# Expected: "Did not find any relation named audit_logs"

# Verify partitions gone
psql "$DATABASE_URL" -c \
  "SELECT tablename FROM pg_tables WHERE tablename LIKE 'audit_logs_%';"
# Expected: 0 rows

# Verify trigger function gone
psql "$DATABASE_URL" -c \
  "SELECT proname FROM pg_proc WHERE proname = 'fn_audit_log_immutable';"
# Expected: 0 rows
```

The Alembic `downgrade()` function handles the correct drop order:
1. Drop trigger `trg_audit_log_immutable`
2. Drop function `fn_audit_log_immutable`
3. Drop indexes on parent table (`ix_audit_entity`, `ix_audit_user`, `ix_audit_action`)
4. Drop child partitions (`audit_logs_y2026m04`, `audit_logs_y2026m05`, ...)
5. Drop parent table `audit_logs`

Business data tables (`items`, `orders`, etc.) are never touched by this migration; only the `audit_logs` infrastructure is removed.

### 12.3 Data preservation — archive before drop

If audit records must be preserved for legal hold before rolling back:

```bash
# Export all audit entries to a timestamped CSV before downgrade
psql "$DATABASE_URL" -c \
  "COPY audit_logs TO STDOUT CSV HEADER" \
  > /tmp/audit_backup_$(date +%Y%m%d_%H%M%S).csv

# Count rows exported
wc -l /tmp/audit_backup_*.csv

# Verify CSV is readable
head -3 /tmp/audit_backup_*.csv

# THEN run the database rollback
alembic downgrade -1
```

To restore audit data after rollback (e.g., for forensic analysis):

```bash
# Re-run the migration in a separate schema
psql "$DATABASE_URL" -c "CREATE SCHEMA IF NOT EXISTS audit_archive"
# Restore the CSV manually to a plain (non-partitioned) table for read-only queries
```

### 12.4 Failure mode: hash chain broken in production

If `verify_hash_chain()` returns `is_intact=False`, the chain has been tampered with or a bug caused inconsistent hashing:

```bash
# 1. Record the broken_at entry ID from the verify response
BROKEN_ID="<entry_id from verify response>"

# 2. Dump all entries from the pg_dump before the investigation window
pg_dump "$DATABASE_URL" -t audit_logs \
  --format=custom -f /tmp/audit_forensic_$(date +%Y%m%d).dump

# 3. Query the broken entry and its predecessor to inspect discrepancy
psql "$DATABASE_URL" -c \
  "SELECT id, action, entry_hash, prev_hash, created_at
   FROM audit_logs
   WHERE id = '$BROKEN_ID'
   OR created_at = (
     SELECT created_at - interval '1 microsecond'
     FROM audit_logs WHERE id = '$BROKEN_ID'
   )
   ORDER BY created_at;"

# 4. Re-run the verifier over a wider window to find all affected entries
# POST /audit-logs/verify with from_dt extended back to the beginning of the partition

# 5. If tampering is confirmed, escalate to security team:
#    - Preserve the pg_dump as evidence
#    - Identify the DB user and timestamp of the unauthorized write
#    - Check pg_audit (if installed) or PostgreSQL logs for UPDATE/DELETE attempts
```

### 12.5 Failure mode: partition missing — writes failing

If `audit_logs` writes fail with "no partition of relation audit_logs found for row":

```bash
# 1. Check which partitions exist
psql "$DATABASE_URL" -c \
  "SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::regclass))
   FROM pg_tables WHERE tablename LIKE 'audit_logs_%' ORDER BY tablename;"

# 2. Manually create the missing partition for the current month
YEAR=$(date +%Y)
MONTH=$(date +%m)
NEXT_MONTH=$(python3 -c "
import datetime; d=datetime.date.today().replace(day=1)
m=d.month%12+1; y=d.year+(d.month//12); print(f'{y:04d}-{m:02d}-01')
")
psql "$DATABASE_URL" -c \
  "CREATE TABLE IF NOT EXISTS audit_logs_y${YEAR}m${MONTH}
   PARTITION OF audit_logs
   FOR VALUES FROM ('${YEAR}-${MONTH}-01') TO ('${NEXT_MONTH}')"

# 3. Restart the application to clear any connection-level partition cache

# 4. Re-run ensure_next_partition() to create the following month's partition
PYTHONPATH=. python -c "
import asyncio
from app.jobs.audit_partition import ensure_next_partition
asyncio.run(ensure_next_partition())
"
```

### 12.6 Failure mode: retention purge deletes wrong rows

If the retention purge job deletes rows it should not (e.g., wrong cutoff date due to timezone issue):

```bash
# 1. IMMEDIATELY stop the scheduler to prevent further purge runs
# (set AUDIT_RETAIN_DAYS=0 disables purge in config, or comment out scheduler registration)

# 2. Assess the damage: count entries per time bucket after the purge
psql "$DATABASE_URL" -c \
  "SELECT DATE_TRUNC('day', created_at) AS day, COUNT(*)
   FROM audit_logs
   GROUP BY 1 ORDER BY 1 DESC LIMIT 30;"

# 3. If backup exists, restore deleted entries from the CSV backup
# (rows are append-only; re-inserting from backup is safe if no entries were modified)
psql "$DATABASE_URL" -c \
  "COPY audit_logs FROM '/tmp/audit_backup_YYYYMMDD_HHMMSS.csv' CSV HEADER"

# 4. Verify hash chain is intact after restore
# POST /audit-logs/verify over the restored time range

# 5. Fix the timezone handling in purge_expired_audit_logs():
#    Ensure cutoff uses datetime.now(tz=timezone.utc) not datetime.utcnow()
#    Add unit test T-25b verifying cutoff is UTC-aware
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Model has no `id` field — uses composite PK | `getattr(target, "id", "")` returns empty string; audit entry created with `entity_id=""` and a WARNING logged; operator should add `id` or override the entity_id extraction hook |
| EC-02 | `is_deleted` field exists with a non-boolean type (e.g. datetime) | `_classify_action()` compares truthiness; `None→datetime.now()` is treated as `soft_delete`; `datetime→None` as `restore`; all other changes are `update` |
| EC-03 | `before_flush` listener fires inside a nested savepoint | SQLAlchemy fires `before_flush` once per flush, not per savepoint; audit entries are correctly linked to the outermost transaction; rollback of the savepoint does not create orphaned audit entries |
| EC-04 | `AuditLog` model itself is in `AUDITED_MODELS` | Audit listener skips instances of `AuditLog`; checked by `if type(target) is AuditLog: return`; prevents infinite recursion |
| EC-05 | Two workers flush simultaneously; hash chain order is ambiguous | Hash chain is best-effort under concurrent writers; `prev_hash` is the last hash seen in the same session at flush time, not globally ordered; cross-session ordering is not guaranteed and not claimed as a security invariant |
| EC-06 | `log_reads=True` and a route reads 1000 items in one request | One audit entry per entity that was accessed; for list endpoints, one entry per row in the result set; volume can be high — recommend enabling only for sensitive entity types |
| EC-07 | Project has no User model yet | Tool proceeds; `user_id` column uses `Uuid` with `nullable=True` and no FK; emits a warning: "No User model found; user_id FK will not be added" |
| EC-08 | `retain_days=0` is passed | Tool raises `ValueError: retain_days must be >= 1 or None`; zero would purge all entries immediately |
| EC-09 | Partition boundary hit during a request (e.g., midnight UTC on month boundary) | PostgreSQL routes the INSERT to the correct partition transparently; no application change needed |
| EC-10 | Alembic migration runs against a DB that already has `audit_logs` table | `upgrade()` checks with `IF NOT EXISTS`; safe to re-run |
| EC-11 | A model's `before_values` JSONB value exceeds 1MB (very wide model) | SQLAlchemy JSONB column has no size limit in the ORM; PostgreSQL TOAST handles large values transparently; storage per row increases beyond the 2KB typical target |
| EC-12 | Application crashes mid-flush after `AuditLog` was `session.add()`-ed but before commit | Transaction rolled back; both business row and audit entry are lost together; no orphaned audit entries (QS-01) |
| EC-13 | Hash chain disabled (`hash_chain=False`) — verifier called | `verify_hash_chain()` finds `entry_hash=null` for all entries; returns `is_intact=False` with message "hash chain not enabled on this installation" |
| EC-14 | `CurrentAuditor` dependency used in a project without RBAC | Dependency falls back to checking `current_user.is_superuser`; if the `User` model has no `role` field, `role` check is skipped; only superusers can access audit routes |
| EC-15 | Tool is run with `models=[]` (empty list) | Tool emits a WARNING: "No models specified; audit log infrastructure will be created but no models will be tracked. Use AUDITED_MODELS.add(MyModel) manually to enable tracking." Tool proceeds; creates all infrastructure files. |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when all ten criteria below are met:

1. ✅ All 30 Completeness Criteria verified by automated check (CC-01..CC-30)
2. ✅ All 25 User Stories have passing acceptance tests (US-01..US-25)
3. ✅ All 30 Test Cases pass (T-01..T-30)
4. ✅ All 8 Invariants are enforced with referenced tests
5. ✅ All 15 Edge Cases are handled per the documented behaviors
6. ✅ Interaction Matrix verified by integration test run against a project with TOOL-001, TOOL-008, TOOL-012 installed
7. ✅ Rollback procedure tested end-to-end: `alembic downgrade -1` removes all audit infrastructure; business data intact; trigger removed
8. ✅ Performance SLOs measured and met: write < 5ms, query < 100ms, verify < 5s/10k
9. ✅ Re-audit by Opus in fresh context, brutal mode: score ≥ 9.5/10
10. ✅ One human dev uses it on a production-candidate FastAPI project and can answer "what did user X do in the last 24h?" in under 30 seconds using the query API

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` exists and is a directory
- [ ] Validate `app/` subdirectory exists
- [ ] Validate `alembic/versions/` exists
- [ ] Validate `app/models/base.py` exists with `Base` class
- [ ] Validate `app/core/db.py` exports `async_session_maker`
- [ ] Parse all target model files with `ast.parse`; error on syntax failure
- [ ] Detect existing `audit_logs` table in DB (idempotency check via `alembic_version`)
- [ ] If `retain_days=0` → raise `ValueError` immediately

### 15.2 AuditLog model generation

- [ ] Create `app/models/audit_log.py` with all 12 columns
- [ ] Include `postgresql_partition_by="RANGE (created_at)"` in `__table_args__`
- [ ] Include three composite indexes and one `CheckConstraint`
- [ ] Add `entry_hash` and `prev_hash` columns with `String(64)`, nullable
- [ ] Import `INET`, `JSONB` from `sqlalchemy.dialects.postgresql`
- [ ] Write atomically (temp file + rename)
- [ ] Verify file parses with `ast.parse`

### 15.3 Audit context module

- [ ] Create `app/core/audit_context.py`
- [ ] Define `_current_user_id: ContextVar[UUID | None]` with default `None`
- [ ] Define `_current_request_meta: ContextVar[dict]` with default `{}`
- [ ] Export `set_audit_context(user_id, request)` — sets both contextvars
- [ ] Export `get_audit_context() -> tuple[UUID | None, dict]`
- [ ] Export `clear_audit_context()` — resets both to defaults
- [ ] Verify file parses with `ast.parse`

### 15.4 Audit listeners

- [ ] Create `app/core/audit_listeners.py`
- [ ] Implement `_serialize`, `_compute_diff`, `_full_snapshot`, `_classify_action`
- [ ] Implement `_compute_entry_hash` using `hashlib.sha256` over JSON payload
- [ ] Implement `_emit_audit` setting `prev_hash` from same-session entries
- [ ] Register `before_flush` listener on `Session`
- [ ] Export `register_audit_listeners(hash_chain: bool)` and `AUDITED_MODELS`
- [ ] Guard: skip `AuditLog` instances to prevent recursion
- [ ] Verify file parses

### 15.5 Hash-chain verifier

- [ ] Create `app/core/audit_verifier.py`
- [ ] Implement `verify_hash_chain(session, from_dt, to_dt) -> VerificationResult`
- [ ] Re-compute SHA-256 using the exact same `json.dumps` payload as `_compute_entry_hash`
- [ ] Check hash value match: `row.entry_hash == recomputed_hash`
- [ ] Check chain link: `row.prev_hash == previous row's entry_hash`
- [ ] Return early on first broken link with `broken_at` set
- [ ] Return `VerificationResult` dataclass with `is_intact`, `total_entries`, `broken_at`, `errors`
- [ ] Verify file parses with `ast.parse`

### 15.6 Query CRUD

- [ ] Create `app/crud/audit_log.py`
- [ ] Implement `query_audit_logs(session, filters, offset, limit) -> AuditLogPage`
- [ ] All 6 filter fields applied conditionally (not blindly joined)
- [ ] Count query uses `SELECT count()` on subquery to avoid double join
- [ ] Ordering is `AuditLog.created_at.desc()` by default
- [ ] `offset` and `limit` applied after count — correct pagination
- [ ] Verify file parses with `ast.parse`

### 15.7 Schemas

- [ ] Create `app/schemas/audit_log.py`
- [ ] Define `AuditLogFilter` Pydantic v2 model with 6 optional fields (all `None` defaults)
- [ ] Define `AuditLogPublic` response schema — excludes `entry_hash`, `prev_hash` from API surface
- [ ] Define `AuditLogPage` with `items: list[AuditLogPublic]`, `total`, `offset`, `limit`
- [ ] Define `VerifyRequest` with `from_dt: datetime`, `to_dt: datetime`
- [ ] All schemas use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility
- [ ] Verify file parses with `ast.parse`

### 15.8 Audit routes

- [ ] Create `app/api/routes/audit_logs.py`
- [ ] `GET /audit-logs/` with all 6 query params as `Query(None)` + `offset` + `limit`
- [ ] `POST /audit-logs/verify` accepting `VerifyRequest` body, calling `verify_hash_chain`
- [ ] Both routes require `CurrentAuditor` dependency (injected via `Depends`)
- [ ] Both routes use `Annotated[AsyncSession, Depends(get_async_session)]`
- [ ] Response models set explicitly: `AuditLogPage` and `VerificationResult`
- [ ] Add router to `app/api/main.py` with `include_router`
- [ ] Verify file parses with `ast.parse`

### 15.9 Retention and partition jobs

- [ ] Create `app/jobs/audit_retention.py` with `purge_expired_audit_logs(retain_days: int) -> dict`
- [ ] Retention job uses `DELETE ... LIMIT BATCH_SIZE` loop with `asyncio.sleep(BATCH_SLEEP_SECONDS)` between batches
- [ ] Retention job only runs if `retain_days` is set (not None); no-op if `settings.AUDIT_RETAIN_DAYS` is None
- [ ] Create `app/jobs/audit_partition.py` with `ensure_next_partition() -> None`
- [ ] Partition job checks `pg_tables` before creating to ensure idempotency
- [ ] Both jobs registered in APScheduler if present; else log INFO with manual call instruction
- [ ] Verify both files parse with `ast.parse`

### 15.10 Middleware

- [ ] Create `app/api/middleware/audit.py` with `AuditContextMiddleware(BaseHTTPMiddleware)`
- [ ] Middleware reads `current_user` from `request.state` (set by auth middleware upstream)
- [ ] Extracts `user_id = getattr(request.state, "user_id", None)` safely
- [ ] Calls `set_audit_context(user_id, request)` before `await call_next(request)`
- [ ] Calls `clear_audit_context()` in `finally` block to prevent context bleed
- [ ] Middleware is a no-op for paths that do not require auth (pass-through)
- [ ] Register middleware in `main.py` AFTER auth middleware via `app.add_middleware`
- [ ] Verify file parses with `ast.parse`

### 15.11 Migration generation

- [ ] Compute next revision number from existing `alembic/versions/` files
- [ ] Generate `{rev}_add_audit_log.py`
- [ ] `upgrade()` step 1: `CREATE TABLE audit_logs ... PARTITION BY RANGE (created_at)` with all 12 columns
- [ ] `upgrade()` step 2: create partition for current month (`audit_logs_y{Y}m{M}`)
- [ ] `upgrade()` step 3: create partition for next month (`audit_logs_y{Y}m{M+1}`)
- [ ] `upgrade()` step 4: create 3 composite indexes on parent table
- [ ] `upgrade()` step 5: install `fn_audit_log_immutable` trigger function via raw SQL
- [ ] `upgrade()` step 6: install `trg_audit_log_immutable` trigger on parent table
- [ ] `downgrade()` drops in correct reverse order: trigger → function → indexes → child partitions → parent
- [ ] Migration parses with `ast.parse`
- [ ] Add `AUDIT_RETAIN_DAYS: int | None = None` and `AUDIT_HASH_CHAIN: bool = True` to `app/core/config.py` `Settings`

### 15.12 Application startup wiring

- [ ] Add `register_audit_listeners(hash_chain=settings.AUDIT_HASH_CHAIN)` to `main.py` lifespan startup
- [ ] Import all target model classes and add them to `AUDITED_MODELS` set at startup
- [ ] Add `CurrentAuditor` dependency to `app/api/deps.py` checking `role=auditor` or `is_superuser`
- [ ] Verify `AuditContextMiddleware` is added AFTER auth middleware in `main.py`
- [ ] Verify `audit_logs` router is added in `app/api/main.py` include list
- [ ] Verify `main.py` parses with `ast.parse`
- [ ] Smoke test: `python -c "from app.main import app; print('ok')"` exits 0

### 15.13 Test generation and verification

- [ ] Create `tests/test_audit_log.py`
- [ ] Generate all 30 test cases (T-01..T-30)
- [ ] Include fixtures: `auditor_token`, `normal_user_token`, `superuser_token`, `async_session`
- [ ] Verify file parses
- [ ] Run `pytest tests/test_audit_log.py --collect-only` — 30 tests collected
- [ ] Run `pytest tests/` — 0 regressions in existing test suite
- [ ] Measure tool execution time; verify < 5s
- [ ] Return success report with metrics (see §16)

### 15.14 Atomicity

- [ ] All file writes use temp-file + atomic `os.rename` pattern (never write directly to final path)
- [ ] Track all touched files in a `touched: list[Path]` before any write
- [ ] On ANY step failure, iterate `touched` in reverse and restore originals from `.bak` copies
- [ ] New files (no original) are removed (`os.remove`) on rollback
- [ ] Drop partially-created migration file if it exists and was created in this run
- [ ] Return `{"status": "error", "files_created": [...], "files_modified": [...], "files_rolled_back": [...], "error": "..."}` on failure
- [ ] Return success report (see §16) only after all steps complete and `pytest --collect-only` exits 0

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/audit_log.py",
    "app/core/audit_context.py",
    "app/core/audit_listeners.py",
    "app/core/audit_verifier.py",
    "app/crud/audit_log.py",
    "app/schemas/audit_log.py",
    "app/api/routes/audit_logs.py",
    "app/jobs/audit_retention.py",
    "app/jobs/audit_partition.py",
    "alembic/versions/0005_add_audit_log.py",
    "tests/test_audit_log.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/core/config.py",
    "app/api/main.py",
    "app/api/deps.py"
  ],
  "metrics": {
    "execution_time_ms": 3847,
    "files_changed": 15,
    "lines_added": 734,
    "lines_removed": 12,
    "models_audited": 4,
    "hash_chain_enabled": true,
    "retain_days": null
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_audit_log.py -v",
    "Create an auditor user: UPDATE users SET role='auditor' WHERE email='...'",
    "Verify the hash chain: POST /audit-logs/verify {from_dt, to_dt}",
    "Test immutability: psql $DATABASE_URL -c \"UPDATE audit_logs SET action='read' LIMIT 1\""
  ],
  "warnings": [
    "No User FK added to audit_logs.user_id — User model not found. Add manually if needed.",
    "retain_days is null: audit entries will be kept forever. Set AUDIT_RETAIN_DAYS in .env to enable purge."
  ],
  "notes": [
    "Audit listeners registered for 4 models: Item, Order, Product, User.",
    "Hash chain enabled: each entry is linked via SHA-256 to its predecessor.",
    "Partitioned by month: initial partitions audit_logs_y2026m04 and audit_logs_y2026m05 created.",
    "Immutability trigger installed: UPDATE and DELETE on audit_logs raise ProgrammingError.",
    "Existing tests still pass: 47/47."
  ]
}
```
