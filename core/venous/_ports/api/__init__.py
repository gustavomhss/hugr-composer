"""Port surface for the ``api`` namespace (17 registered primitives).

WP-15 phase 1 ships hand-authored ports for 2 exemplars:

* :class:`CommandBusProtocol` — dispatch Commands to async handlers.
* :class:`QueryBusProtocol` — dispatch Queries to async handlers.

The remaining 15 primitives in this namespace are catalogued
(see ``../CATALOG.json``) and queued for follow-up port-consumer WPs.
"""

from __future__ import annotations

from core.venous._ports.api.CommandBus import CommandBusProtocol
from core.venous._ports.api.QueryBus import QueryBusProtocol

__all__ = ["CommandBusProtocol", "QueryBusProtocol"]
