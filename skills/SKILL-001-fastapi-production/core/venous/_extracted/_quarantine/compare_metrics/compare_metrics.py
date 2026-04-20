from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession


async def compare_metrics(session: AsyncSession, name: str, version_a: str, version_b: str) -> tuple[MLModel | None, MLModel | None]:
    """Fetch two versions for side-by-side metrics comparison.

    Args:
        session: Active async database session.
        name: Logical model name.
        version_a: First version to compare.
        version_b: Second version to compare.

    Returns:
        Tuple of ``(row_a, row_b)``; either may be ``None`` if not found.
    """
    row_a = await get_by_version(session, name, version_a)
    row_b = await get_by_version(session, name, version_b)
    return (row_a, row_b)
