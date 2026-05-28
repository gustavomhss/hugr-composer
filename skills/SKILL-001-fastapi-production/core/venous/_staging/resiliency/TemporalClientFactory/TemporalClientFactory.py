from __future__ import annotations
from typing import Any


class TemporalClientFactory:
    """Factory that creates and caches a Temporal client singleton.

    All access goes through the module-level ``get_client()`` helper;
    this class exists so tests can substitute a mock without
    monkey-patching module globals.

    Attributes:
        host: Temporal server address (host:port).
        namespace: Temporal namespace for workflow isolation.
    """

    def __init__(self, host: str, namespace: str) -> None:
        """Initialise the factory with server coordinates.

        Args:
            host: Temporal server address (e.g. ``localhost:7233``).
            namespace: Temporal namespace (e.g. ``default``).
        """
        self.host = host
        self.namespace = namespace

    async def connect(self) -> Any:
        """Create a new Temporal client connection.

        Imports ``temporalio.client.Client`` lazily so the module is
        safe to import without the SDK installed.

        Returns:
            A connected ``temporalio.client.Client`` instance.

        Raises:
            ModuleNotFoundError: When ``temporalio`` is not installed.
        """
        from temporalio.client import Client
        client = await Client.connect(self.host, namespace=self.namespace)
        logger.info('Temporal client connected', extra={'host': self.host, 'namespace': self.namespace})
        return client
