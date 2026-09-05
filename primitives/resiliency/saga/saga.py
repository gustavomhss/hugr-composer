"""Pure Python primitive: Saga."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class Saga:
    """Base class for saga orchestrations.

    Subclass and decorate step methods with @saga_step.
    Steps are discovered by inspecting all methods for the
    ``_is_saga_step`` marker attribute.

    Example::

        class MyWorkflow(Saga):
            @saga_step(compensate="undo_a")
            async def step_a(self, context: dict) -> dict:
                return {"a_result": 42}

            async def undo_a(self, context: dict, idempotency_key: str) -> None:
                ...
    """

    @classmethod
    def collect_steps(cls) -> list[dict[str, Any]]:
        """Discover @saga_step methods in declaration order.

        Returns:
            List of dicts with keys: name, compensate_name, timeout.
            Order is determined by source line number for determinism.
        """
        steps = []
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if getattr(method, '_is_saga_step', False):
                try:
                    lineno = inspect.getsourcelines(method)[1]
                except (OSError, TypeError):
                    lineno = 0
                steps.append({'name': name, 'compensate_name': getattr(method, '_compensate_name', None), 'timeout': getattr(method, '_step_timeout', 30), '_lineno': lineno})
        steps.sort(key=lambda s: s['_lineno'])
        for s in steps:
            s.pop('_lineno', None)
        return steps
