from __future__ import annotations
from typing import Any


class RequestReplayer:
    """Re-execute a recorded request against the live ASGI app and diff.

    Args:
        app: The FastAPI ASGI application instance.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def replay(self, record: dict) -> dict:
        """Re-execute *record* and return a diff result dict.

        Args:
            record: A recorded request dict from RequestRecorder.

        Returns:
            Dict with keys: ``id``, ``original_status``,
            ``replayed_status``, ``body_diff``, ``status_changed``.
        """
        import httpx
        method = record.get('method', 'GET')
        path = record.get('path', '/')
        body = record.get('request_body', '')
        headers = {k: v for k, v in (record.get('request_headers') or {}).items() if k.lower() not in ('content-length', 'host', 'transfer-encoding')}
        try:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://replay', headers=headers) as client:
                response = await client.request(method=method, url=path, content=body.encode() if body else b'')
            replayed_body = response.text
            replayed_status = response.status_code
        except Exception as exc:
            logger.warning('Replay request failed: %s', exc, exc_info=True)
            replayed_body = ''
            replayed_status = 500
        orig_status = record.get('status_code', 0)
        orig_body = record.get('response_body', '')
        diff = _diff_bodies(orig_body, replayed_body)
        return {'id': record.get('id'), 'original_status': orig_status, 'replayed_status': replayed_status, 'status_changed': orig_status != replayed_status, 'body_diff': diff, 'diff_count': len(diff)}
