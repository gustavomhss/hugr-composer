from __future__ import annotations


class BrowsingScenario(TaskSet):
    """Read-heavy browsing scenario (70% of simulated traffic).

    Simulates users navigating the catalog, searching, and viewing item
    detail pages without creating or modifying data.
    """

    @task(10)
    @tag('read', 'list')
    def list_items(self) -> None:
        """GET /api/v1/items — most common endpoint."""
        with self.client.get('/api/v1/items', headers=self.user.auth_headers, catch_response=True, name='GET /api/v1/items') as resp:
            if resp.status_code == 200:
                resp.success()
                self.user.last_items = resp.json().get('data', [])
            else:
                resp.failure(f'status {resp.status_code}')

    @task(3)
    @tag('read', 'detail')
    def view_item(self) -> None:
        """GET /api/v1/items/{id} — view a specific item."""
        items = getattr(self.user, 'last_items', [])
        if not items:
            return
        item_id = random.choice(items).get('id')
        self.client.get(f'/api/v1/items/{item_id}', headers=self.user.auth_headers, name='GET /api/v1/items/:id')
