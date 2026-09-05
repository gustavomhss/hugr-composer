"""Worker settings registry."""

from __future__ import annotations

TASK_REGISTRY = {}

class WorkerSettings:
    """Configuration for a background worker."""

    def __init__(self, concurrency: int = 4):
        self.concurrency = concurrency
