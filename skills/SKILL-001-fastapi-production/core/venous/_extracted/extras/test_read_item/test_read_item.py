from __future__ import annotations


@pytest.mark.asyncio
async def test_read_item(async_client: httpx.AsyncClient, auth_headers: dict) -> None:
    """GET /api/v1/items/{id} returns the created item."""
    create_resp = await async_client.post('/api/v1/items/', json={'title': 'Read Test', 'description': 'Read me'}, headers=auth_headers)
    assert create_resp.status_code == 201
    item_id = create_resp.json()['id']
    read_resp = await async_client.get(f'/api/v1/items/{item_id}', headers=auth_headers)
    assert read_resp.status_code == 200, f'Expected 200, got {read_resp.status_code}'
    assert read_resp.json()['id'] == item_id
