from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def replace_recovery_codes(session: AsyncSession, *, device: MFADevice, plaintext_codes: list[str]) -> None:
    """Delete existing recovery codes for *device* and insert new hashed codes.

    Args:
        session: Async SQLAlchemy session.
        device: The MFADevice whose codes to replace.
        plaintext_codes: Fresh plaintext codes from ``generate_recovery_codes()``.
    """
    for old in list(device.recovery_codes):
        await session.delete(old)
    await session.flush()
    for code in plaintext_codes:
        session.add(MFARecoveryCode(id=uuid.uuid4(), device_id=device.id, code_hash=hash_recovery_code(code)))
    await session.flush()
