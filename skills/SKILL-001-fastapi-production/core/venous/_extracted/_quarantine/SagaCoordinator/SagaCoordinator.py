from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from typing import Type
import asyncio
import uuid


class SagaCoordinator:
    """Drives a Saga through its steps with durable state and compensation.

    Args:
        session: Async SQLAlchemy session (coordinator manages commits).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _execute_step(self, saga_obj, step_meta: dict, step_exec, context: dict, completed: list) -> bool:
        """Attempt one saga step; update step_exec state; return True on success.

        Args:
            saga_obj: Instantiated Saga object with step methods.
            step_meta: Step descriptor dict (``name``, ``timeout``).
            step_exec: SagaStepExecution ORM row already added to session.
            context: Mutable execution context dict updated with step output.
            completed: Accumulator list of completed step dicts.

        Returns:
            True if the step succeeded, False if it raised an exception.
        """
        try:
            method = getattr(saga_obj, step_meta['name'])
            output = await asyncio.wait_for(method(context), timeout=step_meta['timeout'])
            step_exec.state = 'completed'
            step_exec.output_data = output or {}
            if output:
                context.update(output)
            completed.append({'meta': step_meta, 'exec': step_exec})
            await self.session.flush()
            return True
        except Exception as exc:
            step_exec.state = 'failed'
            step_exec.error = str(exc)[:512]
            await self.session.flush()
            return False

    async def run(self, saga_cls: Type[Saga], input_data: dict[str, Any], *, saga_id: uuid.UUID | None=None) -> dict[str, Any]:
        """Execute all saga steps in order; compensate on failure.

        Args:
            saga_cls: Saga subclass to instantiate.
            input_data: Initial context passed to each step.
            saga_id: Optional pre-assigned UUID (for idempotent retries).

        Returns:
            Dict with ``saga_id``, ``state``, and ``output_data``.
        """
        sid = saga_id or uuid.uuid4()
        steps = saga_cls.collect_steps()
        instance = SagaInstance(id=sid, saga_type=saga_cls.__name__, state='running', input_data=input_data)
        self.session.add(instance)
        await self.session.flush([instance])
        saga_obj = saga_cls()
        context: dict[str, Any] = dict(input_data)
        completed: list[dict[str, Any]] = []
        for i, step_meta in enumerate(steps):
            step_exec = SagaStepExecution(saga_id=sid, step_number=i, step_name=step_meta['name'], state='running', input_data=context)
            self.session.add(step_exec)
            instance.current_step = i
            await self.session.flush()
            ok = await self._execute_step(saga_obj, step_meta, step_exec, context, completed)
            if not ok:
                instance.error = step_exec.error
                await self._compensate(saga_obj, completed, context, sid)
                instance.state = 'failed'
                instance.completed_at = datetime.now(timezone.utc)
                await self.session.commit()
                return {'saga_id': str(sid), 'state': 'failed', 'error': step_exec.error}
        instance.state = 'completed'
        instance.output_data = context
        instance.completed_at = datetime.now(timezone.utc)
        await self.session.commit()
        return {'saga_id': str(sid), 'state': 'completed', 'output_data': context}

    async def _compensate(self, saga_obj: Saga, completed: list[dict], context: dict, saga_id: uuid.UUID) -> None:
        """Run compensations in strict reverse order.

        Args:
            saga_obj: Saga instance with compensation methods.
            completed: Steps that completed successfully (in forward order).
            context: Current saga context dict.
            saga_id: UUID of the saga instance for idempotency keys.
        """
        for item in reversed(completed):
            meta = item['meta']
            step_exec: SagaStepExecution = item['exec']
            compensate_name = meta.get('compensate_name')
            if not compensate_name:
                continue
            compensate_fn = getattr(saga_obj, compensate_name, None)
            if compensate_fn is None:
                logger.warning('Saga %s missing compensation method %s', saga_id, compensate_name)
                continue
            try:
                idempotency_key = f"{saga_id}:{meta['name']}:compensate"
                await asyncio.wait_for(compensate_fn(context, idempotency_key), timeout=meta['timeout'])
                step_exec.state = 'compensated'
                step_exec.compensation_attempts += 1
                step_exec.compensated_at = datetime.now(timezone.utc)
                await self.session.flush()
                logger.info('Saga %s compensated step %s', saga_id, meta['name'])
            except Exception as exc:
                step_exec.compensation_attempts += 1
                logger.error('Saga %s compensation %s failed: %s', saga_id, compensate_name, exc)
