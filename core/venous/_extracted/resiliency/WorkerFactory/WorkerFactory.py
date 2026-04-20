from __future__ import annotations
from typing import Any


class WorkerFactory:
    """Creates a Temporal worker bound to a task queue.

    Attributes:
        task_queue: Name of the Temporal task queue to poll.
    """

    def __init__(self, task_queue: str) -> None:
        """Initialise the factory with a task queue name.

        Args:
            task_queue: Temporal task queue the worker will poll.
        """
        self.task_queue = task_queue

    async def create(self, client: Any) -> Any:
        """Create a Temporal worker connected to *client*.

        Imports the SDK lazily, applies ``@activity.defn`` to each
        activity function, and registers workflows + activities.

        Args:
            client: Connected ``temporalio.client.Client`` instance.

        Returns:
            A configured ``temporalio.worker.Worker`` instance.
        """
        from temporalio import activity as _act
        from temporalio.worker import Worker
        import app.workflows.activities as _acts
        from app.workflows.example_workflow import OrderProcessingWorkflow
        activity_fns = [_acts.validate_order, _acts.charge_payment, _acts.fulfil_order, _acts.compensate_payment]
        registered = [_act.defn(fn) for fn in activity_fns]
        worker = Worker(client, task_queue=self.task_queue, workflows=[OrderProcessingWorkflow], activities=registered)
        logger.info('Temporal worker created task_queue=%s', self.task_queue)
        return worker
