from __future__ import annotations
import time


class OnboardingProgress:
    """Tracks the progress of a single onboarding run."""

    def __init__(self, onboarding_id: str, tenant_name: str) -> None:
        """Initialise progress tracker."""
        self.onboarding_id = onboarding_id
        self.tenant_name = tenant_name
        self.status = OnboardingStatus.PENDING
        self.current_step: str = ''
        self.completed_steps: list[str] = []
        self.failed_step: str = ''
        self.error: str = ''
        self.started_at: float = time.time()
        self.completed_at: float = 0.0
        self.context: dict = {}

    def to_dict(self) -> dict:
        """Return serialisable snapshot of current progress."""
        return {'onboarding_id': self.onboarding_id, 'tenant_name': self.tenant_name, 'status': self.status.value, 'current_step': self.current_step, 'completed_steps': self.completed_steps, 'failed_step': self.failed_step, 'error': self.error, 'started_at': self.started_at, 'completed_at': self.completed_at}
