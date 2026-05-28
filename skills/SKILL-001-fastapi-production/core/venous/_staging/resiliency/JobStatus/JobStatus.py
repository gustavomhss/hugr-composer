from __future__ import annotations
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle status of a background job.

    Values:
        queued: Waiting in the arq queue, not yet picked up.
        running: Currently being executed by a worker.
        success: Completed successfully; ``result`` is populated.
        failed: Permanently failed after ``max_tries`` attempts.
        cancelled: Aborted by an operator before completion.
    """
    queued = 'queued'
    running = 'running'
    success = 'success'
    failed = 'failed'
    cancelled = 'cancelled'
