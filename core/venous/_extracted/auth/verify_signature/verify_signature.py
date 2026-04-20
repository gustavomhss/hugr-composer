from __future__ import annotations
from fastapi import HTTPException
from fastapi import Request
from fastapi import status


async def verify_signature(request: Request, x_signature: Annotated[str, Header(alias='x-signature')]='', x_timestamp: Annotated[str, Header(alias='x-timestamp')]='', x_nonce: Annotated[str, Header(alias='x-nonce')]='') -> None:
    """FastAPI dependency that verifies the HMAC request signature.

    Raises ``HTTP 401`` when the signature is missing, replayed, or invalid.

    Args:
        request: Incoming FastAPI request.
        x_signature: HMAC-SHA256 signature from request header.
        x_timestamp: Unix timestamp from request header.
        x_nonce: One-time nonce from request header.

    Raises:
        HTTPException: ``401 Unauthorized`` on missing or invalid signature.
    """
    ts = _parse_signing_headers(x_signature, x_timestamp, x_nonce)
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    nonce_store = get_nonce_store()
    if nonce_store.is_replay(x_nonce):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={'detail': 'Request replay detected.'})
    signer = _get_signer()
    window = getattr(settings, 'REQUEST_SIGNING_TIMESTAMP_WINDOW_S', 300)
    valid = signer.verify(method=request.method, path=request.url.path, query=request.url.query or '', headers=headers, body=body, signature=x_signature, timestamp=ts, nonce=x_nonce, window_seconds=window)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={'detail': 'Request signature is invalid.'})
