from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def consume_recovery_code(session: AsyncSession, *, device: MFADevice, code: str) -> bool:
    """Attempt to consume a single-use recovery code.

    Finds the first unused code whose hash matches *code* and marks
    ``used_at`` to prevent reuse.

    Args:
        session: Async SQLAlchemy session.
        device: The MFADevice owning the recovery codes.
        code: Plaintext recovery code provided by the user.

    Returns:
        ``True`` if a matching unused code was found and consumed.
    """
    stmt = select(MFARecoveryCode).where(MFARecoveryCode.device_id == device.id, MFARecoveryCode.used_at.is_(None))
    candidates = (await session.execute(stmt)).scalars().all()
    for row in candidates:
        if verify_recovery_code(code, row.code_hash):
            row.used_at = datetime.now(timezone.utc)
            await session.flush()
            return True
    return False
