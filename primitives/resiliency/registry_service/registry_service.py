"""Pure Python primitive: RegistryService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class RegistryService:
    """Facade for ML model registry operations.

    Attributes:
        session: SQLAlchemy async session (injected via FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an active async session.

        Args:
            session: Active ``AsyncSession`` instance.
        """
        self.session = session

    async def register_model(self, payload: MLModelCreate) -> MLModel:
        """Register a new model version.

        Args:
            payload: Validated create payload.

        Returns:
            The newly inserted ``MLModel`` row.
        """
        return await crud.register(self.session, payload)

    async def promote_to_production(self, name: str, version: str) -> MLModel | None:
        """Promote *version* to production status.

        Args:
            name: Logical model name.
            version: Semantic version to promote.

        Returns:
            Promoted ``MLModel`` row, or ``None`` if version not found.
        """
        return await crud.promote(self.session, name, version)

    async def rollback_to_previous(self, name: str) -> MLModel | None:
        """Roll back current production version to the previous one.

        Args:
            name: Logical model name.

        Returns:
            Restored ``MLModel`` row, or ``None`` if rollback impossible.
        """
        return await crud.rollback(self.session, name)

    async def get_active_model(self, name: str) -> MLModel | None:
        """Return the current production version.

        Args:
            name: Logical model name.

        Returns:
            ``MLModel`` row with status=production, or ``None``.
        """
        return await crud.get_active(self.session, name)

    async def ab_split(self, name: str, version_a: str, version_b: str, percentage: int) -> dict[str, Any]:
        """Configure an A/B percentage rollout between two versions.

        If ``add_feature_toggles_api`` is installed (detected by the
        presence of ``app.crud.feature_toggle``), the rollout is
        persisted to the ``feature_toggles`` table.  Otherwise a stub
        acknowledgement is returned.

        Args:
            name: Logical model name.
            version_a: Version sent to ``(100 - percentage)``% of traffic.
            version_b: Version sent to ``percentage``% of traffic.
            percentage: Integer 0-100 for version_b share.

        Returns:
            Dict with ``name``, ``version_a``, ``version_b``,
            ``percentage``, and ``backend`` keys.
        """
        backend = 'stub'
        try:
            import importlib
            ft_crud = importlib.import_module('app.crud.feature_toggle')
            flag_name = f'ml_ab_{name}'
            await ft_crud.upsert_toggle(self.session, name=flag_name, rollout_percentage=percentage)
            backend = 'feature_toggles'
        except (ImportError, AttributeError):
            logger.debug('feature_toggles not installed; using stub A/B response')
        return {'name': name, 'version_a': version_a, 'version_b': version_b, 'percentage': percentage, 'backend': backend}

    async def build_compare(self, name: str, version_a: str, version_b: str) -> MLModelCompare:
        """Build a side-by-side metrics comparison object.

        Args:
            name: Logical model name.
            version_a: First version.
            version_b: Second version.

        Returns:
            ``MLModelCompare`` with metrics from both versions.
        """
        row_a, row_b = await crud.compare_metrics(self.session, name, version_a, version_b)
        metrics_a = row_a.metrics_json if row_a else None
        metrics_b = row_b.metrics_json if row_b else None
        winner = _pick_winner(version_a, metrics_a, version_b, metrics_b)
        return MLModelCompare(name=name, version_a=version_a, version_b=version_b, metrics_a=metrics_a, metrics_b=metrics_b, winner=winner)
