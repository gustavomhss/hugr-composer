from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession


async def register(session: AsyncSession, payload: MLModelCreate) -> MLModel:
    """Insert a new model version with status=registered.

    Args:
        session: Active async database session.
        payload: Validated create payload.

    Returns:
        The newly created ``MLModel`` row.
    """
    row = MLModel(name=payload.name, version=payload.version, artifact_path=payload.artifact_path, framework=payload.framework, metrics_json=payload.metrics_json, status='registered')
    session.add(row)
    await session.flush()
    await session.refresh(row)
    logger.info('Registered model %s v%s', payload.name, payload.version)
    return row
