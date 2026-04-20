from __future__ import annotations
from fastapi import HTTPException
from fastapi import status
import asyncio


@router.post('/predict', response_model=PredictionResponse, status_code=200)
async def predict(req: PredictionRequest, current_user: CurrentUser) -> PredictionResponse:
    """Run a single model prediction.

    Args:
        req: ``PredictionRequest`` with input, model_name, model_version.
        current_user: Authenticated user (auth gate only).

    Returns:
        ``PredictionResponse`` with output and latency_ms.

    Raises:
        HTTPException(404): Model not registered.
        HTTPException(504): Prediction timed out.
        HTTPException(500): Prediction raised an unexpected error.
    """
    _ = current_user
    predictor = _get_predictor(req.model_name, req.model_version)
    try:
        output, latency_ms = await predictor.predict(req.input)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail={'detail': 'Prediction timed out'})
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={'detail': str(exc)})
    except Exception as exc:
        logger.error('predict endpoint error: %s', exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={'detail': 'Prediction failed'})
    return PredictionResponse(output=output, model_name=req.model_name, model_version=req.model_version, latency_ms=latency_ms)
