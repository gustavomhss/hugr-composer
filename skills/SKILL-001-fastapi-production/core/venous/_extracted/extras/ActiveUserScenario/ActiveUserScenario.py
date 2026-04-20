from __future__ import annotations


class ActiveUserScenario(TaskSet):
    """Mixed read/write scenario (25% of simulated traffic).

    Simulates users creating items, updating their profile, and browsing.
    """

    @task(6)
    @tag('read', 'list')
    def list_items(self) -> None:
        """GET /api/v1/items."""
        self.client.get('/api/v1/items', headers=self.user.auth_headers, name='GET /api/v1/items')

    @task(4)
    @tag('write', 'create')
    def create_item(self) -> None:
        """POST /api/v1/items — create a new item."""
        self.client.post('/api/v1/items', json=make_item_create(), headers=self.user.auth_headers, name='POST /api/v1/items')

    @task(2)
    @tag('read', 'me')
    def get_my_profile(self) -> None:
        """GET /api/v1/users/me — fetch the authenticated user's profile."""
        self.client.get('/api/v1/users/me', headers=self.user.auth_headers, name='GET /api/v1/users/me')
