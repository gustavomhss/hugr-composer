from __future__ import annotations
from typing import Any


async def run_export(ctx: dict, *, job_id: str, user_id: str, model: str, format: str, filters: dict[str, Any]) -> dict[str, Any]:
    """ARQ job entrypoint. Streams rows to storage, emails presigned URL.

    Args:
        ctx: ARQ job context (contains ``session``, ``redis``, etc.).
        job_id: Unique export job UUID (string).
        user_id: UUID string of the requesting user.
        model: Model name string (e.g. ``"Item"``).
        format: Export format — ``csv``, ``json``, ``xlsx``, or ``parquet``.
        filters: Column filters to apply when building the export query.

    Returns:
        Dict with ``job_id``, ``url``, and ``status``.

    Raises:
        ValueError: If ``format`` is not a recognised export format.
    """
    gen_fn = _GENERATORS.get(format)
    if gen_fn is None:
        raise ValueError(f'run_export: unknown format={format!r}')
    from app.core.export_progress import ExportStatus, set_export_progress
    from app.core.model_registry import build_filtered_stmt, get_model_class
    session = ctx['session']
    storage = get_storage()
    redis = ctx.get('redis')
    if redis:
        await set_export_progress(redis, job_id, ExportStatus.RUNNING)
    model_cls = get_model_class(model)
    stmt = build_filtered_stmt(model_cls, filters)
    cols = [c.name for c in model_cls.__table__.columns if c.name not in __import__('app.core.export', fromlist=['SENSITIVE_COLUMNS']).SENSITIVE_COLUMNS]
    url = await _stream_export_to_storage(session, storage, gen_fn, stmt, cols, job_id, format)
    if redis:
        await set_export_progress(redis, job_id, ExportStatus.COMPLETE, download_url=url)
    _try_send_email(ctx, user_id, model, url, job_id)
    logger.info('export_complete job_id=%s model=%s format=%s user=%s', job_id, model, format, user_id)
    return {'job_id': job_id, 'url': url, 'status': 'complete'}
