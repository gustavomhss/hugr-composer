"""Protocol for RpcInterceptor — generated from RpcInterceptor.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class RpcInterceptor(Protocol):
    """RpcInterceptor primitive — gRPC-style per-call middleware contract."""

    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes: ...
