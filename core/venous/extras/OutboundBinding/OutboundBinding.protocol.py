"""Protocol for OutboundBinding — generated from OutboundBinding.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class OutboundBinding(Protocol):
    """OutboundBinding primitive — declarative adapter for external-system invocation."""

    async def invoke(self, request: BindingInvocation) -> tuple[bytes, Mapping[str, str]]: ...
