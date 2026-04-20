from __future__ import annotations


@pytest.mark.asyncio
async def test_login_returns_token(async_client: httpx.AsyncClient, test_user: dict) -> None:
    """POST /api/v1/auth/login returns a JWT access_token."""
    resp = await async_client.post('/api/v1/auth/login', data={'username': test_user['email'], 'password': test_user['password']})
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'
    body = resp.json()
    assert 'access_token' in body, f'access_token missing from response: {body}'
    assert body.get('token_type', '').lower() == 'bearer', f'token_type not bearer: {body}'
