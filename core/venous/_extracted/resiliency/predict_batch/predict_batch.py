from __future__ import annotations
from fastapi import HTTPException
from fastapi import status
import asyncio


@router.post('/predict/batch', response_model=BatchPredictionResponse, status_code=200)
async def predict_batch(req: BatchPredictionRequest, current_user: CurrentUser) -> BatchPredictionResponse:
    """Run batch predictions (respects ML_MAX_BATCH_SIZE).

    Args:
        req: ``BatchPredictionRequest`` with inputs list, model_name, version.
        current_user: Authenticated user (auth gate only).

    Returns:
        ``BatchPredictionResponse`` with outputs list and total latency_ms.

    Raises:
        HTTPException(422): Batch exceeds ML_MAX_BATCH_SIZE.
        HTTPException(404): Model not registered.
        HTTPException(504): Prediction timed out.
        HTTPException(500): Unexpected error.
    """
    _ = current_user
    if len(req.inputs) > settings.ML_MAX_BATCH_SIZE:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={'detail': f'Batch size {len(req.inputs)} exceeds limit {settings.ML_MAX_BATCH_SIZE}'})
    predictor = _get_predictor(req.model_name, req.model_version)
    try:
        outputs, latency_ms = await predictor.predict_batch(req.inputs, max_batch_size=settings.ML_MAX_BATCH_SIZE)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={'detail': 'Batch prediction timed out'})
    except Exception as exc:
        logger.error('predict_batch endpoint error: %s', exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={'detail': 'Batch prediction failed'})
    return BatchPredictionResponse(outputs=outputs, model_name=req.model_name, model_version=req.model_version, latency_ms=latency_ms, count=len(outputs))
