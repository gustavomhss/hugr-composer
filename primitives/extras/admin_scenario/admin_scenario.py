"""Locust scenario: AdminScenario."""

from __future__ import annotations
from locust import TaskSet, task

class AdminScenario(TaskSet):
    """Admin user scenario."""

    @task
    def example_task(self):
        pass
