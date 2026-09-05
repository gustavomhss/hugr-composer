"""Locust scenario: BrowsingScenario."""

from __future__ import annotations
from locust import TaskSet, task

class BrowsingScenario(TaskSet):
    """Browsing user scenario."""

    @task
    def example_task(self):
        pass
