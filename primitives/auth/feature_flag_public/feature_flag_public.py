"""Pure Python primitive: FeatureFlagPublic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class FeatureFlagPublic:
    """Output schema for feature-flag API responses.

    Attributes:
        id: UUID primary key.
        created_at: UTC creation timestamp.
        updated_at: UTC last-updated timestamp.
        updated_by: UUID of the last actor.
    """
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    updated_by: uuid.UUID | None = None
