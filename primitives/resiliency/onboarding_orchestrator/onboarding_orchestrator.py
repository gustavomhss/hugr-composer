"""Pure Python primitive: OnboardingOrchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class OnboardingOrchestrator:
    """Executes an ordered list of onboarding steps with compensation.

    Steps are executed in registration order. On failure at step N,
    steps 0..N-1 are compensated in reverse order.
    """

    def __init__(self, steps: list[OnboardingStep] | None=None) -> None:
        """Initialise orchestrator with optional list of steps."""
        self._steps: list[OnboardingStep] = steps or []

    def add_step(self, step: OnboardingStep) -> None:
        """Append a step to the pipeline."""
        self._steps.append(step)

    def start(self, tenant_name: str, admin_email: str) -> OnboardingProgress:
        """Begin onboarding for a new tenant.

        Args:
            tenant_name: The display name of the new tenant.
            admin_email: Email address for the tenant admin user.

        Returns:
            ``OnboardingProgress`` that can be polled for status.
        """
        onboarding_id = str(uuid.uuid4())
        progress = OnboardingProgress(onboarding_id=onboarding_id, tenant_name=tenant_name)
        progress.context['tenant_name'] = tenant_name
        progress.context['admin_email'] = admin_email
        _PROGRESS_REGISTRY[onboarding_id] = progress
        progress.status = OnboardingStatus.RUNNING
        completed: list[OnboardingStep] = []
        for step in self._steps:
            progress.current_step = step.name
            logger.info('Onboarding %s: executing step %s', onboarding_id, step.name)
            try:
                step.execute(progress.context)
                completed.append(step)
                progress.completed_steps.append(step.name)
                logger.info('Onboarding %s: step %s completed', onboarding_id, step.name)
            except Exception as exc:
                progress.status = OnboardingStatus.FAILED
                progress.failed_step = step.name
                progress.error = str(exc)
                logger.error('Onboarding %s: step %s FAILED: %s', onboarding_id, step.name, exc)
                self._compensate(onboarding_id, progress, completed)
                return progress
        progress.status = OnboardingStatus.COMPLETED
        progress.current_step = ''
        progress.completed_at = time.time()
        logger.info('Onboarding %s: all steps completed', onboarding_id)
        return progress

    def _compensate(self, onboarding_id: str, progress: OnboardingProgress, completed: list[OnboardingStep]) -> None:
        """Execute compensation (rollback) for all completed steps in reverse."""
        progress.status = OnboardingStatus.COMPENSATING
        for step in reversed(completed):
            try:
                step.compensate(progress.context)
                logger.info('Onboarding %s: compensated step %s', onboarding_id, step.name)
            except Exception as exc:
                logger.error('Onboarding %s: compensation of step %s failed: %s', onboarding_id, step.name, exc)
        progress.status = OnboardingStatus.COMPENSATED
