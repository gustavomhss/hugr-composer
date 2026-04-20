from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession


async def update(session: AsyncSession, *, toggle: FeatureToggle, toggle_in: ToggleUpdate) -> FeatureToggle:
    """Apply a partial update to a FeatureToggle.

    Args:
        session: Async SQLAlchemy session.
        toggle: Existing FeatureToggle ORM instance.
        toggle_in: Validated partial update schema.

    Returns:
        Updated FeatureToggle ORM instance.
    """
    for field, value in toggle_in.model_dump(exclude_unset=True).items():
        setattr(toggle, field, value)
    await session.flush()
    await session.refresh(toggle)
    return toggle
