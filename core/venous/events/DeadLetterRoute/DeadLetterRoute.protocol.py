"""Protocol for DeadLetterRoute — generated from DeadLetterRoute.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterator, Mapping, Sequence

@runtime_checkable
class DeadLetterSink(Protocol):
    """DeadLetterRoute primitive — named destination for undeliverable events."""

    async def send(self, route: DeadLetterRoute, envelope: EventEnvelope, reason: str, attempt: int) -> None: ...

@runtime_checkable
class RequeueTarget(Protocol):
    """DeadLetterRoute primitive — named destination for undeliverable events."""

    async def republish(self, topic: str, envelope: EventEnvelope) -> None: ...
