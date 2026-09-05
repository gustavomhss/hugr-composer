"""Pure Python primitive: FlagContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class FlagContext:
    """Caller-provided evaluation context for targeting rules.

    Attributes:
        user_id: UUID of the requesting user (used for bucketing).
        tenant_id: UUID of the requesting tenant (optional).
        environment: Runtime environment string, e.g. 'production'.
        attributes: Arbitrary extra attributes for custom rules.
    """
    __slots__ = ('user_id', 'tenant_id', 'environment', 'attributes')

    def __init__(self, user_id: UUID | None=None, tenant_id: UUID | None=None, environment: str='production', attributes: dict[str, Any] | None=None) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.environment = environment
        self.attributes = attributes or {}
