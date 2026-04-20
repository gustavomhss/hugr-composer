from __future__ import annotations


@pytest.mark.asyncio
async def test_update_item(async_client: httpx.AsyncClient, auth_headers: dict) -> None:
    """PATCH /api/v1/items/{id} updates the item title."""
    create_resp = await async_client.post('/api/v1/items/', json={'title': 'Before Update', 'description': 'Will be updated'}, headers=auth_headers)
    assert create_resp.status_code == 201
    item_id = create_resp.json()['id']
    update_resp = await async_client.patch(f'/api/v1/items/{item_id}', json={'title': 'After Update'}, headers=auth_headers)
    assert update_resp.status_code == 200, f'Expected 200, got {update_resp.status_code}: {update_resp.text}'
    assert update_resp.json()['title'] == 'After Update'
