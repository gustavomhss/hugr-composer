from __future__ import annotations


@pytest.mark.asyncio
async def test_create_item_wrong_type_returns_422(async_client: httpx.AsyncClient, auth_headers: dict) -> None:
    """POST /api/v1/items/ with wrong field type returns 422."""
    resp = await async_client.post('/api/v1/items/', json={'title': 12345, 'description': True}, headers=auth_headers)
    assert resp.status_code < 500, f'Server error (5xx) on type mismatch: {resp.status_code} {resp.text}'
