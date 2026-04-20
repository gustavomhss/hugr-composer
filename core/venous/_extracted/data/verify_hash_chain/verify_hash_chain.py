from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def verify_hash_chain(session: AsyncSession, from_dt: datetime, to_dt: datetime) -> VerificationResult:
    """Re-compute SHA-256 hashes and verify chain continuity.

    Args:
        session: Async SQLAlchemy session.
        from_dt: Start of the verification range (inclusive).
        to_dt: End of the verification range (inclusive).

    Returns:
        VerificationResult with is_intact=True if all hashes are valid.
    """
    stmt = select(AuditLog).where(AuditLog.created_at.between(from_dt, to_dt)).order_by(AuditLog.created_at)
    rows = (await session.execute(stmt)).scalars().all()
    result = VerificationResult(total_entries=len(rows))
    prev_hash: str | None = None
    for row in rows:
        ok, error_msg = _verify_row(row, prev_hash)
        if not ok:
            result.is_intact = False
            result.broken_at = str(row.id)
            result.errors.append(error_msg)
            break
        prev_hash = row.entry_hash
    return result
