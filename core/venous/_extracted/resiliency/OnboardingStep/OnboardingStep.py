from __future__ import annotations
from typing import Protocol


class OnboardingStep(Protocol):
    """Protocol that every onboarding step must satisfy."""

    @property
    def name(self) -> str:
        """Return a unique name for this step."""
        ...

    def execute(self, context: dict) -> None:
        """Execute the step. Raises on failure."""
        ...

    def compensate(self, context: dict) -> None:
        """Compensate (undo) the step. Must be idempotent."""
        ...
