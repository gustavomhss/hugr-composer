from __future__ import annotations
from fastapi import Response


@schemathesis.check
def validate_error_response_structure(response: Response, case: Case) -> None:
    """Assert 4xx responses contain a ``detail`` or ``errors`` key.

    Args:
        response: HTTP response from the ASGI app.
        case: Associated schemathesis test case.
    """
    if 400 <= response.status_code < 500:
        try:
            data = response.json()
        except Exception:
            return
        assert 'detail' in data or 'errors' in data, f'Error response from {case.formatted_path} missing detail/errors: {data}'
