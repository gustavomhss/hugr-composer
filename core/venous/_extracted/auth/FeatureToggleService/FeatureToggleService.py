from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import os
import time


class FeatureToggleService:
    """Service layer for feature toggle evaluation and administration.

    Provides ``is_enabled`` for hot-path callers and CRUD wrappers for
    the admin API.  All results are cached in-process for
    ``FEATURE_TOGGLES_CACHE_TTL_SECONDS`` seconds.

    Attributes:
        _session: Async SQLAlchemy session injected at construction time.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_enabled(self, name: str, *, user_id: str | None=None, environment: str='production', default: bool=False) -> bool:
        """Return whether a toggle is active for the given context.

        Checks env-var override first, then in-memory cache, then DB.

        Args:
            name: Toggle name string.
            user_id: Optional user ID for per-user rules.
            environment: Current runtime environment.
            default: Fallback when toggle is missing or evaluation fails.

        Returns:
            True if the toggle is active for this context, else False.
        """
        env_val = os.getenv(name.upper(), '').strip().lower()
        if env_val in _TRUTHY:
            return True
        if env_val in _FALSY:
            return False
        toggle = await self._load(name)
        if toggle is None:
            return default
        enabled, _ = evaluate(toggle, user_id=user_id, environment=environment)
        return enabled

    async def create_toggle(self, toggle_in: ToggleCreate) -> ToggleRead:
        """Create a new feature toggle and invalidate cache.

        Args:
            toggle_in: Validated create schema.

        Returns:
            ToggleRead schema of the newly created toggle.
        """
        toggle = await create(self._session, toggle_in=toggle_in)
        _invalidate(toggle.name)
        return ToggleRead.model_validate(toggle)

    async def update_toggle(self, name: str, toggle_in: ToggleUpdate) -> ToggleRead | None:
        """Update a toggle and invalidate cache.

        Args:
            name: Toggle name to update.
            toggle_in: Validated partial update schema.

        Returns:
            Updated ToggleRead, or None if toggle not found.
        """
        toggle = await get_by_name(self._session, name=name)
        if toggle is None:
            return None
        toggle = await update(self._session, toggle=toggle, toggle_in=toggle_in)
        _invalidate(toggle.name)
        return ToggleRead.model_validate(toggle)

    async def list_toggles(self) -> list[ToggleRead]:
        """Return all toggles as ToggleRead schemas.

        Returns:
            List of ToggleRead schemas ordered by name.
        """
        rows = await list_toggles(self._session)
        return [ToggleRead.model_validate(r) for r in rows]

    async def _load(self, name: str) -> object | None:
        """Load toggle from cache or DB.

        Args:
            name: Toggle name string.

        Returns:
            FeatureToggle ORM instance or None.
        """
        entry = _CACHE.get(name)
        if entry is not None:
            cached_at, value = entry
            if time.monotonic() - cached_at < _CACHE_TTL:
                return value
        toggle = await get_by_name(self._session, name=name)
        _CACHE[name] = (time.monotonic(), toggle)
        return toggle
