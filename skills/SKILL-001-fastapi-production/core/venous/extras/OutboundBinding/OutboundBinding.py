"""OutboundBinding primitive — declarative adapter for external-system invocation.

Implements the catalog Protocol for `extras.OutboundBinding` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- OBND-INV-01: the `operation` field MUST be one of the operations declared by
  the binding component; unknown values SHALL be rejected.
- OBND-INV-02: `binding_name` ALWAYS refers to a component already registered;
  an unresolved name CANNOT invoke anything.
- OBND-INV-03: metadata keys NEVER include secrets in plaintext because binding
  metadata can be logged by observability layers.
- OBND-INV-04: binary payloads MUST round-trip unchanged; the adapter CANNOT
  mutate data bytes implicitly.
- OBND-INV-05: invocation timeouts SHALL be honored by the adapter or
  explicitly surfaced as a deadline error.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Heuristic secret-signature patterns that MUST NOT appear in metadata values.
_SECRET_SIGNATURES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),        # Anthropic
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),            # OpenAI / generic
    re.compile(r"AKIA[0-9A-Z]{16}"),                 # AWS access key
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),            # Google API
    re.compile(r"ghp_[A-Za-z0-9]{36}"),              # GitHub PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),     # Slack
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}"), # Bearer tokens in metadata
)

# Keys that look like password/secret/token fields — value content MUST NOT
# be accepted in metadata under any circumstances. Value-regex scanning (the
# `_SECRET_SIGNATURES` tuple) catches LONG-form tokens but leaks short test
# keys (`sk-xyz`) — key-pattern scanning catches anything named `token` /
# `authorization` / `credential` even when the value is too short to
# trigger the value regex. Defense in depth.
_SECRET_KEY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"api[-_]?key", re.IGNORECASE),
    re.compile(r"private[-_]?key", re.IGNORECASE),
    re.compile(r"^token$|[-_]token$|^token[-_]|[-_]token[-_]", re.IGNORECASE),
    re.compile(r"authorization|auth[-_]?token", re.IGNORECASE),
    re.compile(r"credential|cred[-_]?id", re.IGNORECASE),
    re.compile(r"access[-_]?key", re.IGNORECASE),
    re.compile(r"refresh[-_]?token", re.IGNORECASE),
    re.compile(r"session[-_]?id", re.IGNORECASE),
)


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class OutboundBindingError(ValueError):
    """Raised when a call violates an OutboundBinding invariant."""


class BindingDeadlineExceededError(TimeoutError):
    """Raised when an adapter honors the declared timeout (OBND-INV-05)."""


# ---------------------------------------------------------------------------
# Dataclasses (mirror the catalog api_signature)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BindingInvocation:
    binding_name: str
    operation: str
    data: bytes
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class OutboundBinding(Protocol):
    async def invoke(self, request: BindingInvocation) -> tuple[bytes, Mapping[str, str]]: ...


# A registered binding component = declared allowed operations + execute fn.
ExecuteFn = Callable[[BindingInvocation], Awaitable[tuple[bytes, Mapping[str, str]]]]


@dataclass(frozen=True)
class BindingComponent:
    name: str
    allowed_operations: frozenset[str]
    execute: ExecuteFn


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
def validate_metadata_secrets(metadata: Mapping[str, str]) -> None:
    """OBND-INV-03: reject secret-looking metadata values."""
    for k, v in metadata.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise OutboundBindingError(
                f"OBND-INV-03 supporting: metadata entries MUST be str/str, got {type(k).__name__}/{type(v).__name__}."
            )
        for sig in _SECRET_SIGNATURES:
            if sig.search(v):
                raise OutboundBindingError(
                    f"OBND-INV-03: metadata value for {k!r} matches a credential pattern; NEVER include secrets in plaintext."
                )
        for kp in _SECRET_KEY_PATTERNS:
            if kp.search(k):
                raise OutboundBindingError(
                    f"OBND-INV-03: metadata key {k!r} looks like a secret field; FORBIDDEN in binding metadata."
                )


def validate_invocation(
    req: BindingInvocation,
    registry: Mapping[str, BindingComponent],
) -> BindingComponent:
    """OBND-INV-01 + OBND-INV-02 + OBND-INV-03 + OBND-INV-04."""
    if not isinstance(req.binding_name, str) or not req.binding_name:
        raise OutboundBindingError(
            "OBND-INV-02 supporting: binding_name MUST be a non-empty string."
        )
    if req.binding_name not in registry:
        raise OutboundBindingError(
            f"OBND-INV-02: binding {req.binding_name!r} is not registered; CANNOT invoke."
        )
    component = registry[req.binding_name]
    if req.operation not in component.allowed_operations:
        raise OutboundBindingError(
            f"OBND-INV-01: operation {req.operation!r} unknown for binding "
            f"{req.binding_name!r}; allowed={sorted(component.allowed_operations)}."
        )
    if not isinstance(req.data, (bytes, bytearray, memoryview)):
        raise OutboundBindingError(
            f"OBND-INV-04: data MUST be bytes-like, got {type(req.data).__name__}."
        )
    validate_metadata_secrets(req.metadata)
    return component


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
class InMemoryOutboundBinding:
    """Reference OutboundBinding that dispatches to a static registry.

    Designed for tests; real deployments swap in a Dapr-style client.
    """

    def __init__(
        self,
        components: Mapping[str, BindingComponent],
        *,
        default_timeout_s: float = 5.0,
    ) -> None:
        if default_timeout_s <= 0:
            raise OutboundBindingError(
                "OBND-INV-05 supporting: default_timeout_s MUST be > 0."
            )
        self._registry: dict[str, BindingComponent] = dict(components)
        self._default_timeout_s = default_timeout_s
        self._invocations: int = 0

    async def invoke(
        self,
        request: BindingInvocation,
        *,
        timeout_s: float | None = None,
    ) -> tuple[bytes, Mapping[str, str]]:
        component = validate_invocation(request, self._registry)
        # OBND-INV-04: pass bytes to the adapter without mutation.
        original = bytes(request.data)
        call = component.execute(BindingInvocation(
            binding_name=request.binding_name,
            operation=request.operation,
            data=original,
            metadata=dict(request.metadata),
        ))
        budget = timeout_s if timeout_s is not None else self._default_timeout_s
        if budget <= 0:
            raise OutboundBindingError("OBND-INV-05: timeout_s MUST be > 0.")
        try:
            out_bytes, out_md = await asyncio.wait_for(call, timeout=budget)
        except asyncio.TimeoutError as e:
            raise BindingDeadlineExceededError(
                f"OBND-INV-05: binding {request.binding_name!r} operation "
                f"{request.operation!r} exceeded deadline {budget}s."
            ) from e
        self._invocations += 1
        if not isinstance(out_bytes, (bytes, bytearray, memoryview)):
            raise OutboundBindingError(
                f"OBND-INV-04: adapter return MUST be bytes, got {type(out_bytes).__name__}."
            )
        return bytes(out_bytes), dict(out_md)

    @property
    def invocations(self) -> int:
        return self._invocations


__all__ = [
    "BindingComponent",
    "BindingDeadlineExceededError",
    "BindingInvocation",
    "ExecuteFn",
    "InMemoryOutboundBinding",
    "OutboundBinding",
    "OutboundBindingError",
    "validate_invocation",
    "validate_metadata_secrets",
]
