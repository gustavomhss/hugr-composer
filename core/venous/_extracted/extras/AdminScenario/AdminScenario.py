from __future__ import annotations


class AdminScenario(TaskSet):
    """Admin-only scenario (5% of simulated traffic).

    Exercises superuser endpoints that require elevated privileges.
    """

    @task(3)
    @tag('admin', 'users')
    def list_users(self) -> None:
        """GET /api/v1/users — list all users (admin only)."""
        self.client.get('/api/v1/users', headers=self.user.auth_headers, name='GET /api/v1/users (admin)')

    @task(1)
    @tag('admin', 'health')
    def check_health(self) -> None:
        """GET /api/v1/utils/health-check — infrastructure health."""
        self.client.get('/api/v1/utils/health-check', headers=self.user.auth_headers, name='GET /health')
