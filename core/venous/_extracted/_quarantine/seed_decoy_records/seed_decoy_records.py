from __future__ import annotations


async def seed_decoy_records(session: object) -> list[str]:
    """Attempt to insert decoy user records into the users table.

    Silently skips if the users table does not exist or the model
    does not have the expected columns.  Always safe to call.

    Args:
        session: SQLAlchemy ``AsyncSession`` instance.

    Returns:
        List of emails successfully seeded.
    """
    seeded: list[str] = []
    try:
        from sqlalchemy import text
        for decoy in _DECOY_USERS:
            stmt = text('INSERT INTO users (id, email, full_name, is_superuser, is_active, hashed_password) VALUES (:id, :email, :full_name, :is_superuser, :is_active, :hashed_password) ON CONFLICT (email) DO NOTHING')
            await session.execute(stmt, {**decoy, 'hashed_password': 'canary_not_a_real_hash'})
            seeded.append(decoy['email'])
        await session.commit()
        logger.info('canary_seeder: seeded %d decoy records', len(seeded))
    except Exception as exc:
        logger.debug('canary_seeder: skipped (table may not exist yet): %s', exc)
    return seeded
