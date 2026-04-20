from __future__ import annotations


@pytest_asyncio.fixture
async def test_user(async_client: httpx.AsyncClient) -> dict:
    """Create and return a registered test user.

    Returns:
        Dict with ``email`` and ``password`` keys.
    """
    from app.core.config import settings
    email = getattr(settings, 'E2E_TEST_EMAIL', 'e2e_test@example.com')
    password = getattr(settings, 'E2E_TEST_PASSWORD', 'E2eTestPass123!')
    resp = await async_client.post('/api/v1/auth/register', json={'email': email, 'password': password})
    assert resp.status_code in (201, 409), f'Failed to create test user: {resp.status_code} {resp.text}'
    return {'email': email, 'password': password}
