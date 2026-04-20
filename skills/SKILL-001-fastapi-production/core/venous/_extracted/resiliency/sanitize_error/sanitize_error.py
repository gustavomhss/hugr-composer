from __future__ import annotations


def sanitize_error(status_code: int, detail: object, request_id: str='') -> str:
    """Return a safe client-facing message; log the real detail.

    Args:
        status_code: HTTP status code of the response.
        detail: The original exception detail (never sent to client).
        request_id: Optional correlation ID for log correlation.

    Returns:
        A generic, non-leaking error message string.
    """
    logger.error('armor.error_sanitized', extra={'status_code': status_code, 'detail': str(detail), 'request_id': request_id})
    return _GENERIC_MESSAGES.get(status_code, _DEFAULT_GENERIC)
