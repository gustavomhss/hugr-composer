from __future__ import annotations


@pytest.mark.asyncio
async def test_delete_item_then_verify_gone(async_client: httpx.AsyncClient, auth_headers: dict) -> None:
    """DELETE /api/v1/items/{id} removes the item; subsequent GET returns 404."""
    create_resp = await async_client.post('/api/v1/items/', json={'title': 'To Delete', 'description': 'Delete me'}, headers=auth_headers)
    assert create_resp.status_code == 201
    item_id = create_resp.json()['id']
    delete_resp = await async_client.delete(f'/api/v1/items/{item_id}', headers=auth_headers)
    assert delete_resp.status_code in (200, 204), f'Expected 200/204, got {delete_resp.status_code}'
    gone_resp = await async_client.get(f'/api/v1/items/{item_id}', headers=auth_headers)
    assert gone_resp.status_code == 404, f'Expected 404 after delete, got {gone_resp.status_code}'
