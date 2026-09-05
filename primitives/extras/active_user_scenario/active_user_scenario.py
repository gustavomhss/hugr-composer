"""Locust scenario: ActiveUserScenario."""

from __future__ import annotations
from locust import TaskSet, task

class ActiveUserScenario(TaskSet):
    """Active user scenario."""

    @task
    def example_task(self):
        pass
